"""The Librus APIX integration."""

import asyncio
import logging
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from librus_apix.client import Client, Token, new_client
from librus_apix.exceptions import TokenError
from requests.cookies import RequestsCookieJar

# Moduly ladowane razem z integracja: HA importuje ja w executorze, a import
# wewnatrz funkcji async blokowalby petle zdarzen przy pierwszym uzyciu (start HA).
import bs4  # noqa: F401
import soupsieve  # noqa: F401
import librus_apix.announcements  # noqa: F401
import librus_apix.attendance  # noqa: F401
import librus_apix.completed_lessons  # noqa: F401
import librus_apix.grades  # noqa: F401
import librus_apix.homework  # noqa: F401
import librus_apix.messages  # noqa: F401
import librus_apix.schedule  # noqa: F401
import librus_apix.student_information  # noqa: F401
import librus_apix.timetable  # noqa: F401

from .const import DOMAIN
from .sensor import LibrusDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _z_tracebackiem() -> bool:
    """Traceback w logu bledu tylko przy wlaczonym debugu.

    Gdy Librus nie odpowiada, kazda metoda loguje blad - pelne tracebacki
    w kazdym cyklu zasmiecalyby log. Do diagnozy wystarczy wlaczyc debug.
    """
    return _LOGGER.isEnabledFor(logging.DEBUG)


def _current_semester() -> int:
    """Zwroc numer biezacego semestru (1 lub 2) wg polskiego roku szkolnego.

    Semestr 1: wrzesien (9) - styczen (1)
    Semestr 2: luty (2) - czerwiec (6)
    Lipiec-sierpien to wakacje - zwracamy 2 (ostatni semestr roku).
    """
    m = date.today().month
    return 1 if m >= 9 else 2

def _iso_date(d: str) -> str:
    """Znormalizuj date do formatu RRRR-MM-DD (jesli sie da)."""
    from datetime import datetime

    d = (d or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(d, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return d


def _rodzaj_zdarzenia(tytul: str, href: str) -> str:
    """Rozpoznaj rodzaj wpisu terminarza po tytule i adresie szczegolow.

    - szczegoly_wolne/...: "Nauczyciel: ..." to nieobecnosc nauczyciela,
      pozostale (np. "Swieto Niepodleglosci: SP") to dni wolne,
    - bez odnosnika: zastepstwa ("Zastepstwo ...", "X na lekcji nr: 6 (...)"),
      przesuniecia i odwolania,
    - szczegoly/...: kategoria wpisana przez nauczyciela (sprawdzian,
      kartkowka, ...), nieznane kategorie to "wydarzenie".
    """
    t = (tytul or "").strip().lower()
    h = href or ""
    if "szczegoly_wolne" in h:
        return "nieobecnosc_nauczyciela" if t.startswith("nauczyciel") else "dzien_wolny"
    if "przesunięcie" in t or "przesuniecie" in t:
        return "przesuniecie"
    if "odwołan" in t or "odwolan" in t:
        return "odwolanie"
    if "zastępstwo" in t or "zastepstwo" in t or " na lekcji nr" in t:
        return "zastepstwo"
    if any(x in t for x in ("sprawdzian", "klasówka", "klasowka", "praca klasowa", "test")):
        return "sprawdzian"
    if "kartkówka" in t or "kartkowka" in t:
        return "kartkowka"
    return "wydarzenie"


def is_exam_event(event: dict) -> bool:
    """Sprawdz czy wpis terminarza to sprawdzian / kartkowka / klasowka."""
    if not isinstance(event, dict):
        return False
    rodzaj = (event.get("rodzaj") or "").lower()
    if rodzaj in ("sprawdzian", "kartkowka"):
        return True
    t = (event.get("tytul") or "").lower()
    return any(x in t for x in ("sprawdzian", "kartkówka", "kartkowka", "klasówka", "klasowka", "praca klasowa", "test"))


def nowy_klient() -> Client:
    """Nowy klient librus-apix z własnym tokenem i słoikiem ciasteczek.

    W librus-apix 1.5.3 Client ma domyślne argumenty extra_cookies=RequestsCookieJar()
    i token=Token(), tworzone raz przy imporcie, a new_client() nie przekazuje
    ciasteczek. Wszystkie konta (np. dwoje dzieci) dzielą więc jeden słoik, w tym
    oauth_token. Przy kilku kontach zapytania do gateway API (uwagi, frekwencja,
    zajęcia dodatkowe) szły z tokenem innego konta i zwracały dane innego dziecka.
    """
    client = new_client(token=Token())
    client.cookies = RequestsCookieJar()
    return client


def _get_oauth_token(client) -> str | None:
    """Bezpiecznie pobierz token OAuth bez wywoływania CookieConflictError."""
    token_obj = getattr(client, "token", None)
    if token_obj and getattr(token_obj, "oauth", None):
        return token_obj.oauth
    cookies = getattr(client, "cookies", None)
    if cookies and hasattr(cookies, "__iter__"):
        for c in cookies:
            if getattr(c, "name", None) == "oauth_token" and c.value:
                return c.value
    return None


def _set_oauth_cookie(jar, oauth_val: str) -> None:
    """Ustaw ciasteczko oauth_token z domeną synergia.librus.pl, usuwając duplikaty."""
    if jar is None or not hasattr(jar, "set"):
        return
    try:
        to_remove = [c for c in jar if getattr(c, "name", None) == "oauth_token"]
        for c in to_remove:
            jar.clear(c.domain, c.path, c.name)
    except Exception as clear_ex:
        _LOGGER.debug("Błąd czyszczenia zduplikowanych ciasteczek oauth_token: %s", clear_ex)
    try:
        jar.set("oauth_token", oauth_val, domain="synergia.librus.pl", path="/")
    except Exception as set_ex:
        _LOGGER.debug("Błąd ustawiania ciasteczka oauth_token: %s", set_ex)


def _ensure_oauth(client, force_refresh: bool = False) -> str | None:
    """Zapewnij token OAuth bez nadmiarowych zapytań ani konfliktów ciasteczek."""
    oauth = _get_oauth_token(client)
    if oauth and not force_refresh:
        _set_oauth_cookie(getattr(client, "cookies", None), oauth)
        return oauth
    try:
        oauth = client.refresh_oauth()
        if oauth:
            _set_oauth_cookie(getattr(client, "cookies", None), oauth)
        return oauth
    except Exception as ex:
        _LOGGER.debug("Błąd odświeżania tokena OAuth: %s", ex)
        return None


# Linia "Klucz: wartosc" w opisie oceny (Kategoria:, Data:, Nauczyciel: ...)
_KLUCZ_OPISU = re.compile(r"^[A-ZĄĆĘŁŃÓŚŹŻ][\w .()/-]{0,40}: ")


def _opis_oceny(desc: str) -> str:
    r"""Wyciagnij slowny opis oceny z pola desc biblioteki librus-apix.

    librus-apix sklada desc jako "Ocena: <symbol>\nPrzedmiot: <przedmiot>\n"
    + tresc atrybutu title. Przy ocenach tekstowych/symbolicznych (np. "T",
    "np") w title jest dodatkowa linia "Ocena: <opis>", czasem wielowierszowa,
    np. "Ocena: Diagnoza\n\n12/20p\n\n60%". Zwraca opis (linie laczone " · ")
    albo "" gdy go nie ma.
    """
    lines = (desc or "").split("\n")[2:]  # pomijamy linie dodane przez biblioteke
    opis = []
    for i, line in enumerate(lines):
        if line.startswith("Ocena: "):
            opis.append(line[len("Ocena: "):].strip())
            for nxt in lines[i + 1:]:
                if _KLUCZ_OPISU.match(nxt):
                    break
                if nxt.strip():
                    opis.append(nxt.strip())
            break
    return " · ".join(x for x in opis if x)
def _parse_point_grades(html) -> list:
    """Odczytaj oceny z sekcji "Oceny punktowe" strony ocen.

    librus_apix.grades.get_grades pomija te wiersze (maja mniej kolumn niz
    tabela zwyklych ocen). Wiersz przedmiotu rozpoznajemy po obrazku
    z id "przedmioty_OP_<id>"; komorki (bez pierwszej): przedmiot,
    oceny I okresu, wynik I, oceny II okresu, wynik II, wynik roczny.
    Opis oceny jest w atrybucie title odnosnika, np.
    "Kategoria: Aktywnosc (0-100)<br>Data: 2026-09-21 (pon.)<br>...".
    """
    import html as html_lib
    import re

    from bs4 import BeautifulSoup

    # html moze byc juz sparsowanym BeautifulSoup (jedno parsowanie strony ocen)
    soup = BeautifulSoup(html, "lxml") if isinstance(html, (str, bytes)) else html
    result = []
    for img in soup.select('img[id^="przedmioty_OP_"]'):
        row = img.find_parent("tr")
        if row is None or row.get("id"):
            continue  # wiersz ze szczegolami (ukryty) ma id - pomijamy
        cells = [td for td in row.find_all("td", recursive=False) if "screen-only" not in (td.get("class") or [])]
        if len(cells) < 2:
            continue
        subject = cells[0].get_text(" ", strip=True)
        for semester, idx in ((1, 1), (2, 3)):
            if idx >= len(cells):
                continue
            for a in cells[idx].select("span.grade-box > a"):
                title = html_lib.unescape(a.get("title", ""))
                attrs = {}
                for part in re.split(r"<br\s*/?>", title):
                    if ": " in part:
                        key, value = part.split(": ", 1)
                        attrs[key.strip()] = value.strip()
                category = attrs.get("Kategoria", "")
                max_points = None
                m = re.search(r"\(\s*(\d+)\s*-\s*(\d+)\s*\)\s*$", category)
                if m:
                    max_points = int(m.group(2))
                    category = category[: m.start()].strip()
                value = a.get_text(strip=True)
                percent = None
                try:
                    if max_points:
                        percent = round(float(value.replace(",", ".")) * 100 / max_points, 1)
                except ValueError:
                    pass
                result.append({
                    "subject": subject,
                    "grade": value,
                    "date": _iso_date(attrs.get("Data", "")[:10]),
                    "category": category,
                    "teacher": attrs.get("Nauczyciel", ""),
                    "semester": semester,
                    "komentarz": attrs.get("Komentarz", ""),
                    "type": "points",
                    "max_points": max_points,
                    "percent": percent,
                    "counts": attrs.get("Licz do wyniku", "").upper() == "TAK",
                })
    return result


def _parse_behavior_grades(html) -> Optional[dict]:
    """Odczytaj oceny i punkty zachowania ze strony ocen.

    Wyszukuje wiersz "Zachowanie" (np. znacznik z id 'przedmioty_zachowanie_node')
    oraz powiązaną podtabelę '#przedmioty_zachowanie'.
    Zwraca słownik z punktami startowymi, sumami per okres, przewidywanymi ocenami
    oraz listą poszczególnych wpisów punktowych.
    """
    import html as html_lib
    import re
    from bs4 import BeautifulSoup

    # html moze byc juz sparsowanym BeautifulSoup (jedno parsowanie strony ocen)
    soup = BeautifulSoup(html, "lxml") if isinstance(html, (str, bytes)) else html

    node = soup.select_one('#przedmioty_zachowanie_node')
    sub_table = soup.select_one('#przedmioty_zachowanie')

    main_row = None
    if node:
        main_row = node.find_parent("tr")
    else:
        for tr in soup.find_all("tr"):
            for td in tr.find_all("td"):
                if td.get_text(strip=True).lower() == "zachowanie":
                    main_row = tr
                    break
            if main_row:
                break

    if not main_row and not sub_table:
        return None

    result = {
        "punkty_startowe": None,
        "suma_okres_1": None,
        "suma_okres_2": None,
        "ocena_przewidywana_okres_1": "",
        "ocena_przewidywana_okres_2": "",
        "ocena_srodroczna": "",
        "ocena_roczna": "",
        "wpisy": [],
    }

    # 1. Odczyt z podtabeli szczegółowej, jeśli istnieje
    if sub_table:
        current_period = 1
        for tr in sub_table.find_all("tr"):
            tr_text = tr.get_text(" ", strip=True)
            if "Okres 1" in tr_text:
                current_period = 1
                continue
            elif "Okres 2" in tr_text:
                current_period = 2
                continue

            if "Punkty startowe" in tr_text:
                for td in tr.find_all("td"):
                    val = td.get_text(strip=True)
                    if val.replace(".", "", 1).replace("-", "", 1).isdigit():
                        pts = float(val) if "." in val else int(val)
                        result["punkty_startowe"] = pts
                        break
            elif "Suma" in tr_text:
                for td in tr.find_all("td"):
                    val = td.get_text(strip=True)
                    if val.replace(".", "", 1).replace("-", "", 1).isdigit():
                        pts = float(val) if "." in val else int(val)
                        if current_period == 1:
                            result["suma_okres_1"] = pts
                        else:
                            result["suma_okres_2"] = pts
                        break
            elif "Ocena śródroczna przewidywana" in tr_text:
                parts = tr_text.split(":", 1)
                if len(parts) > 1:
                    val = parts[1].strip()
                    if val and val != "-":
                        result["ocena_przewidywana_okres_1"] = val
            elif "Ocena roczna przewidywana" in tr_text:
                parts = tr_text.split(":", 1)
                if len(parts) > 1:
                    val = parts[1].strip()
                    if val and val != "-":
                        result["ocena_przewidywana_okres_2"] = val

    # 2. Odczyt ze znaczków ocen w wierszu głównym
    if main_row:
        cells = [td for td in main_row.find_all("td", recursive=False) if "screen-only" not in (td.get("class") or [])]

        if len(cells) > 2:
            val = cells[2].get_text(strip=True)
            if val and val != "-":
                result["ocena_srodroczna"] = val
        if len(cells) > 4:
            val = cells[4].get_text(strip=True)
            if val and val != "-":
                result["ocena_roczna"] = val

        period_mapping = [(1, 1), (2, 3)]
        for period, col_idx in period_mapping:
            if col_idx >= len(cells):
                continue
            td = cells[col_idx]

            if result["punkty_startowe"] is None:
                start_span = td.select_one('span.tooltip[title*="Punkty startowe"], span[title*="Punkty startowe"]')
                if start_span:
                    st_val = start_span.get_text(strip=True)
                    if st_val.isdigit():
                        result["punkty_startowe"] = int(st_val)

            for a in td.select("span.grade-box > a"):
                title = html_lib.unescape(a.get("title", ""))
                val_text = a.get_text(strip=True)

                parent_box = a.find_parent("span", class_="grade-box")
                box_class = parent_box.get("class", []) if parent_box else []
                is_negative = "negative-behaviour" in box_class or val_text.startswith("-")
                typ = "negatywny" if is_negative else "pozytywny"

                kategoria = ""
                data_wyst = ""
                nauczyciel = ""
                komentarz = ""

                parts = re.split(r"<br\s*/?>", title)
                if parts:
                    first_line = parts[0].strip()
                    m = re.match(r"^(.*?)(?:\((?:[-+]?\d+)\))?$", first_line)
                    kategoria = m.group(1).strip() if m else first_line

                for part in parts[1:]:
                    part_str = part.strip()
                    if part_str.startswith("Data wystawienia:"):
                        data_wyst = part_str.split(":", 1)[1].strip()
                    elif part_str.startswith("Dodał:"):
                        nauczyciel = part_str.split(":", 1)[1].strip()
                    elif part_str.startswith("Komentarz:"):
                        komentarz = part_str.split(":", 1)[1].strip()

                punkty = None
                try:
                    punkty = float(val_text.replace(",", ".")) if "." in val_text or "," in val_text else int(val_text)
                except ValueError:
                    pass

                result["wpisy"].append({
                    "kategoria": kategoria,
                    "punkty": punkty,
                    "typ": typ,
                    "data": data_wyst,
                    "nauczyciel": nauczyciel,
                    "komentarz": komentarz,
                    "okres": period,
                })

    result["wpisy"].sort(key=lambda x: x.get("data") or "", reverse=True)
    return result


def _parse_completed_lessons(html: str) -> list:
    """Sparsuj tabele strony "Zrealizowane lekcje".

    Kolumny: Data | Dzien | Nr lekcji | Przedmiot, nauczyciel | Temat | Z |
    [e-Tablica] | Frekwencja. Liczba kolumn rozni sie miedzy szkolami, wiec
    frekwencje bierzemy z odnosnika w ramce (p.box > a) albo z ostatniej
    kolumny. Zastepstwo Librus oznacza nazwiskiem zastepcy w nawiasie
    kwadratowym: "Kowalska Anna [Nowak Maria]".
    """
    import re
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    lessons = []
    for tr in soup.select('table[class="decorated"] > tbody > tr'):
        data_td = tr.select_one("td.center.small")
        dzien_td = tr.select_one("td.tiny")
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td", attrs={"class": None})]
        if len(cells) < 3:
            continue

        try:
            numer = int(cells[0])
        except ValueError:
            numer = None

        parts = re.split(r"\s*,\s*", cells[1], maxsplit=1)
        przedmiot = parts[0].strip()
        nauczyciel = parts[1].strip() if len(parts) > 1 else ""
        zastepca = ""
        m = re.match(r"^(.*?)\s*\[(.+)\]\s*$", nauczyciel)
        if m:
            nauczyciel, zastepca = m.group(1).strip(), m.group(2).strip()

        obecnosc = ""
        obecnosc_opis = ""
        box = tr.select_one("p.box a")
        if box is not None:
            obecnosc = box.get_text(strip=True)
            m = re.search(r"Rodzaj:\s*([^<]+)", box.get("title", ""))
            if m:
                obecnosc_opis = m.group(1).strip()
        elif len(cells) >= 4:
            obecnosc = cells[-1]

        lessons.append({
            "data": _iso_date(data_td.get_text(strip=True) if data_td else ""),
            "dzien_tygodnia": dzien_td.get_text(strip=True) if dzien_td else "",
            "numer": numer,
            "przedmiot": przedmiot,
            "nauczyciel": nauczyciel,
            "zastepca": zastepca,
            "zastepstwo": bool(zastepca),
            "temat": cells[2],
            "obecnosc": obecnosc,
            "obecnosc_opis": obecnosc_opis,
        })
    return lessons


PLATFORMS = ["sensor", "calendar", "todo", "button", "binary_sensor"]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class LibrusApiClient:
    """Class to interface with the Librus API."""

    # Blokada ponownego logowania po bledzie (sekundy): 5 min, 10, 20 ... max 2 h.
    # Chroni konto przed seria nieudanych logowan (np. po zmianie hasla).
    AUTH_BACKOFF_START = 300
    AUTH_BACKOFF_MAX = 7200

    def __init__(self, username: str, password: str, options: dict = None, hass: HomeAssistant = None):
        """Initialize the client."""
        self.username = username
        self.password = password
        self.options = options or {}
        self.hass = hass
        self._client: Client = None
        self._token = None
        self._auth_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._pending_message_hrefs = []
        self._message_cache = {}
        self._store = Store(hass, 1, f"{DOMAIN}_messages_cache_{self.username}") if hass else None
        self._bg_fetch_task = None
        self.coordinator = None
        self._behavior_data = None
        self._grades_attempted = False
        self._auth_failures = 0
        self._auth_blocked_until = 0.0

    async def async_init_cache(self) -> None:
        """Load cached message contents from persistent store."""
        if self._store:
            try:
                cached = await self._store.async_load()
                if isinstance(cached, dict):
                    self._message_cache.update(cached)
                    _LOGGER.debug("Zaladowano %d wiadomosci z trwalego cache dla %s", len(self._message_cache), self.username)
            except Exception as ex:
                _LOGGER.warning("Nie udalo sie wczytac cache wiadomosci dla %s: %s", self.username, ex)

    async def async_save_cache(self) -> None:
        """Save cached message contents to persistent store."""
        if self._store:
            try:
                if len(self._message_cache) > 100:
                    keys = list(self._message_cache.keys())
                    for k in keys[:-100]:
                        self._message_cache.pop(k, None)
                await self._store.async_save(self._message_cache)
            except Exception as ex:
                _LOGGER.warning("Nie udalo sie zapisac cache wiadomosci dla %s: %s", self.username, ex)

    def _start_background_message_fetcher(self, hrefs: list) -> None:
        """Start background task to gently fetch message contents one by one."""
        if not self.hass:
            return

        if not hasattr(self, "_pending_message_hrefs"):
            self._pending_message_hrefs = []
        for h in hrefs:
            if h not in self._pending_message_hrefs and h not in self._message_cache:
                self._pending_message_hrefs.append(h)

        if self._bg_fetch_task and not self._bg_fetch_task.done():
            return

        async def _fetcher():
            from librus_apix.messages import message_content
            from contextlib import nullcontext
            loop = asyncio.get_running_loop()
            updated_any = False

            while self._pending_message_hrefs:
                href = self._pending_message_hrefs.pop(0)
                if href in self._message_cache:
                    continue

                lock = getattr(self, "_session_lock", None) or nullcontext()
                success = False
                try:
                    async with lock:
                        if not self._client or not self._token:
                            if not await self.async_authenticate():
                                _LOGGER.debug("Brak uwierzytelnienia dla zadania w tle, przerywam kolejkę")
                                self._pending_message_hrefs.insert(0, href)
                                break
                        msg_data = await loop.run_in_executor(None, message_content, self._client, href)
                        content_str = msg_data.content if hasattr(msg_data, 'content') else str(msg_data)
                        formatted_content = content_str.replace("\n", "<br>") if isinstance(content_str, str) else content_str
                        self._message_cache[href] = formatted_content
                        updated_any = True
                        success = True
                        _LOGGER.debug("Pobrano tresc wiadomosci w tle dla %s", href)
                except Exception as ex:
                    _LOGGER.debug("Blad pobierania tresci wiadomosci %s w tle: %s", href, ex)

                # Odstęp czasowy POZA blokadą sesji, aby nie blokować innych zadań ani koordynatora
                await asyncio.sleep(1.5 if success else 1.0)

            if updated_any:
                await self.async_save_cache()
                if self.coordinator and self.coordinator.data:
                    msgs = self.coordinator.data.get("wiadomosci", [])
                    for m in msgs:
                        h = m.get("href")
                        if h in self._message_cache:
                            m["content"] = self._message_cache[h]
                    self.coordinator.async_update_listeners()

        self._bg_fetch_task = self.hass.async_create_task(_fetcher())

    def _reset_auth(self) -> None:
        """Reset authentication state to force re-authentication on next call."""
        orig_close = getattr(self, "_orig_session_close", None)
        if orig_close and self._client and hasattr(self._client, "_session"):
            try:
                orig_close()
            except Exception:
                pass
        self._orig_session_close = None
        self._client = None
        self._token = None

    async def async_authenticate(self):
        """Authenticate with Librus API."""
        async with self._auth_lock:
            now = time.monotonic()
            if now < self._auth_blocked_until:
                _LOGGER.debug(
                    "Pomijam logowanie %s po wcześniejszym błędzie (ponowna próba za %d s)",
                    self.username, int(self._auth_blocked_until - now),
                )
                return False
            try:
                loop = asyncio.get_running_loop()
                self._client = await loop.run_in_executor(None, nowy_klient)
                if hasattr(self._client, "_session") and hasattr(self._client._session, "request"):
                    _orig_request = self._client._session.request
                    def _request_with_timeout(*args, **kwargs):
                        kwargs.setdefault("timeout", 15)
                        return _orig_request(*args, **kwargs)
                    self._client._session.request = _request_with_timeout

                    # Keep-Alive: zapobieganie zamykaniu puli połączeń TCP/TLS przez 'with self._session as s:'
                    if hasattr(self._client._session, "close") and not getattr(self, "_orig_session_close", None):
                        self._orig_session_close = self._client._session.close
                        self._client._session.close = lambda: None

                self._token = await loop.run_in_executor(
                    None, self._client.get_token, self.username, self.password
                )
                _LOGGER.debug("Authentication successful for %s", self.username)
                self._auth_failures = 0
                self._auth_blocked_until = 0.0
                return True
            except Exception as ex:
                self._auth_failures += 1
                blokada = min(
                    self.AUTH_BACKOFF_START * 2 ** (self._auth_failures - 1),
                    self.AUTH_BACKOFF_MAX,
                )
                self._auth_blocked_until = time.monotonic() + blokada
                _LOGGER.error(
                    "Authentication failed (%d z rzędu, kolejna próba najwcześniej za %d min): %s",
                    self._auth_failures, blokada // 60, ex, exc_info=_z_tracebackiem(),
                )
                self._reset_auth()
                return False

    async def async_get_grades(self):
        """Get grades from Librus."""
        self._grades_attempted = True
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None
                client = self._client

                def _fetch_grades_data():
                    html = client.post(
                        client.GRADES_URL, data={"zmiany_logowanie_wszystkie": "1"}
                    ).text
                    from bs4 import BeautifulSoup
                    from librus_apix.grades import (
                        no_access_check,
                        _extract_grades_numeric,
                        _extract_grades_descriptive,
                        ParseError,
                    )
                    soup = no_access_check(BeautifulSoup(html, "lxml"))
                    tr = soup.find_all("tr", attrs={"class": ["line0", "line1"], "id": None})
                    if len(tr) < 1:
                        raise ParseError("Error in parsing grades")
                    num_grades, avg_grades = _extract_grades_numeric(tr)
                    desc_grades = _extract_grades_descriptive(tr)
                    # Ten sam soup dla ocen punktowych i zachowania - strona
                    # ocen jest najwieksza, parsujemy ja tylko raz.
                    try:
                        point_grades = _parse_point_grades(soup)
                    except Exception as pt_ex:
                        _LOGGER.debug("Nie udało się odczytać ocen punktowych: %s", pt_ex)
                        point_grades = []
                    try:
                        behavior_data = _parse_behavior_grades(soup)
                    except Exception as beh_ex:
                        _LOGGER.debug("Nie udało się odczytać zachowania: %s", beh_ex)
                        behavior_data = None
                    return num_grades, avg_grades, desc_grades, point_grades, behavior_data

                loop = asyncio.get_running_loop()
                numeric_grades, average_grades, descriptive_grades, point_grades, behavior_data = await loop.run_in_executor(
                    None, _fetch_grades_data
                )
                self._behavior_data = behavior_data

                current_sem = _current_semester()
                _LOGGER.debug("Filtrowanie ocen dla semestru %d", current_sem)

                # Process all grades
                all_grades = []

                # Process numeric grades (only current semester)
                for subject_grades in numeric_grades:
                    for subject, grades_list in subject_grades.items():
                        for grade in grades_list:
                            if grade.semester != current_sem:
                                continue
                            
                            # Extract comment if available (as string)
                            komentarz_str = ""
                            comments_obj = getattr(grade, 'comments', None)
                            if comments_obj:
                                if isinstance(comments_obj, list):
                                    komentarz_str = " | ".join(c.text for c in comments_obj if hasattr(c, 'text'))
                                elif hasattr(comments_obj, 'text'):
                                    komentarz_str = comments_obj.text
                                else:
                                    komentarz_str = str(comments_obj)
                            
                            if not komentarz_str:
                                desc_text = getattr(grade, 'desc', '') or ''
                                for line in desc_text.splitlines():
                                    if line.startswith("Komentarz:"):
                                        komentarz_str = line.split(":", 1)[1].strip()
                                        break
                                    
                            all_grades.append({
                                'subject': subject,
                                'grade': grade.grade,
                                'date': grade.date,
                                'category': grade.category,
                                'teacher': getattr(grade, 'teacher', ''),
                                'semester': grade.semester,
                                'komentarz': komentarz_str,
                                'opis': _opis_oceny(getattr(grade, 'desc', '')),
                                'type': 'numeric'
                            })

                # Process descriptive grades (only current semester, many are actually numeric)
                for subject_grades in descriptive_grades:
                    for subject, grades_list in subject_grades.items():
                        for desc_grade in grades_list:
                            if desc_grade.semester != current_sem:
                                continue
                            grade_val = desc_grade.grade.strip()
                            
                            is_valid = False
                            if grade_val:
                                clean_val = grade_val.replace('+', '').replace('-', '')
                                if clean_val.isdigit():
                                    is_valid = True
                                elif clean_val.upper() in ['A', 'B', 'C', 'D', 'E', 'F']:
                                    is_valid = True
                                else:
                                    import re
                                    if re.search(r'^(\d+)(?:\s*(?:%|p|pkt))?$', grade_val.lower()):
                                        is_valid = True
                                        
                            if is_valid:
                                
                                desc_text = getattr(desc_grade, 'desc', '')
                                parsed_cat = ""
                                parsed_skill = ""
                                parsed_teacher = getattr(desc_grade, 'teacher', '')
                                parsed_comment = ""
                                
                                for line in desc_text.split('\n'):
                                    if line.startswith("Kategoria:"):
                                        parsed_cat = line.split(":", 1)[1].strip()
                                    elif line.startswith("Umiejętność:"):
                                        parsed_skill = line.split(":", 1)[1].strip()
                                    elif not parsed_teacher and line.startswith("Nauczyciel:"):
                                        parsed_teacher = line.split(":", 1)[1].strip()
                                    elif line.startswith("Komentarz:"):
                                        parsed_comment = line.split(":", 1)[1].strip()
                                
                                final_cat = parsed_cat
                                if not final_cat and parsed_skill:
                                    final_cat = parsed_skill
                                elif not final_cat:
                                    final_cat = desc_text.split('\n')[0] if desc_text else ''

                                all_grades.append({
                                    'subject': subject,
                                    'grade': desc_grade.grade,
                                    'date': desc_grade.date,
                                    'category': final_cat,
                                    'teacher': parsed_teacher,
                                    'semester': desc_grade.semester,
                                    'komentarz': parsed_comment,
                                    'opis': _opis_oceny(desc_text),
                                    'type': 'descriptive'
                                })

                # Oceny punktowe pobrane z tego samego żądania
                for g in point_grades:
                    if g.get("semester") == current_sem:
                        all_grades.append(g)

                return all_grades

            except TokenError as ex:
                _LOGGER.debug(
                    "Token expired fetching grades (attempt %d/2), re-authenticating...",
                    attempt + 1,
                )
                self._reset_auth()
                if attempt == 1:
                    _LOGGER.error("Failed to get grades after re-authentication.")
                    return None
            except Exception as ex:
                if type(ex).__name__ == "ParseError":
                    _LOGGER.debug("Brak lub błąd parsowania ocen (np. konto bez dostępu do ocen): %s", ex)
                    return []
                _LOGGER.error(
                    "Failed to get grades: %s",
                    ex, exc_info=_z_tracebackiem(),
                )
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_behavior(self) -> Optional[dict]:
        """Pobierz dane ocen i punktów z zachowania ze strony ocen.

        Zachowanie jest na tej samej stronie co oceny. Jeśli oceny były już
        pobierane (także nieudanie), nie wysyłamy drugiego zapytania.
        """
        if self._behavior_data is not None or self._grades_attempted:
            return self._behavior_data
        await self.async_get_grades()
        return self._behavior_data

    async def async_get_messages(self, count: int = 10):
        """Get latest messages from Librus (subject and sender only, no content fetch to avoid marking as read)."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None
                client = self._client

                from librus_apix.messages import get_received, message_content

                loop = asyncio.get_running_loop()
                messages = []
                seen = set()
                page = 0
                # Librus dla numeru strony poza zakresem zwraca ponownie ostatnią stronę,
                # więc kończymy, gdy strona nie wnosi nic nowego (bezpiecznik: 10 stron).
                while len(messages) < count and page < 10:
                    page_msgs = await loop.run_in_executor(None, get_received, client, page)
                    new_msgs = [m for m in page_msgs or [] if m.href not in seen]
                    if not new_msgs:
                        break
                    seen.update(m.href for m in new_msgs)
                    messages.extend(new_msgs)
                    page += 1
                messages = messages[:count] if messages else []
                
                fetch_content = self.options.get("fetch_messages_content", False)

                result = []
                missing_content_hrefs = []
                for msg in messages:
                    msg_dict = {
                        "author": msg.author,
                        "title": msg.title,
                        "date": msg.date,
                        "href": msg.href,
                        "unread": msg.unread,
                        "has_attachment": msg.has_attachment,
                    }
                    if fetch_content or not msg.unread:
                        if msg.href in self._message_cache:
                            msg_dict["content"] = self._message_cache[msg.href]
                        else:
                            msg_dict["content"] = None
                            missing_content_hrefs.append(msg.href)
                    else:
                        msg_dict["content"] = None
                    
                    result.append(msg_dict)

                if missing_content_hrefs and self.hass:
                    self._start_background_message_fetcher(missing_content_hrefs)

                return result

            except TokenError as ex:
                _LOGGER.debug(
                    "Token expired fetching messages (attempt %d/2), re-authenticating...",
                    attempt + 1,
                )
                self._reset_auth()
                if attempt == 1:
                    _LOGGER.error("Failed to get messages after re-authentication.")
                    return None
            except Exception as ex:
                _LOGGER.error(
                    "Failed to get messages: %s",
                    ex, exc_info=_z_tracebackiem(),
                )
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_homework(self):
        """Get upcoming homework assignments from Librus (next 30 days)."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None

                from librus_apix.homework import get_homework
                from datetime import date as _date, timedelta

                today = _date.today()
                date_from = today.strftime("%Y-%m-%d")
                date_to = (today + timedelta(days=30)).strftime("%Y-%m-%d")

                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(
                    None, get_homework, self._client, date_from, date_to
                )

            except TokenError:
                _LOGGER.debug(
                    "Token expired fetching homework (attempt %d/2), re-authenticating...",
                    attempt + 1,
                )
                self._reset_auth()
                if attempt == 1:
                    _LOGGER.error("Failed to get homework after re-authentication.")
                    return None
            except Exception as ex:
                _LOGGER.error(
                    "Failed to get homework: %s",
                    ex, exc_info=_z_tracebackiem(),
                )
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_schedule(self):
        """Get upcoming calendar events from Librus (current + next month, filtered to future dates)."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None

                from librus_apix.schedule import get_schedule
                from datetime import date as _date
                import calendar

                today = _date.today()
                loop = asyncio.get_running_loop()

                def _fetch_two_months():
                    events = []
                    for year, month in [
                        (today.year, today.month),
                        (
                            today.year + 1 if today.month == 12 else today.year,
                            1 if today.month == 12 else today.month + 1,
                        ),
                    ]:
                        monthly = get_schedule(self._client, str(month).zfill(2), str(year))
                        for day_num, day_events in monthly.items():
                            event_date = _date(year, month, int(day_num))
                            if event_date < today:
                                continue
                            dni = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
                            for ev in day_events:
                                szczegoly = {}
                                last_key = None
                                for k, v in (ev.data or {}).items():
                                    if v == "unknown" and last_key:
                                        szczegoly[last_key] += f"\n{k}"
                                    elif last_key == "Opis" and k not in ("Data dodania", "Nauczyciel", "Przedmiot", "Kategoria"):
                                        szczegoly[last_key] += f"\n{k}: {v}"
                                    else:
                                        szczegoly[k] = v
                                        last_key = k

                                events.append({
                                    "data": event_date.strftime("%Y-%m-%d"),
                                    "tydzien": dni[event_date.weekday()],
                                    "tytul": ev.title,
                                    "rodzaj": _rodzaj_zdarzenia(ev.title, ev.href),
                                    "przedmiot": ev.subject,
                                    "godzina": ev.hour,
                                    "numer_lekcji": ev.number,
                                    "szczegoly": szczegoly,
                                    "href": ev.href,
                                    "data_dodania": getattr(ev, "add_date", ""),
                                })
                    return sorted(events, key=lambda e: e["data"])

                return await loop.run_in_executor(None, _fetch_two_months)

            except TokenError:
                _LOGGER.debug(
                    "Token expired fetching schedule (attempt %d/2), re-authenticating...",
                    attempt + 1,
                )
                self._reset_auth()
                if attempt == 1:
                    _LOGGER.error("Failed to get schedule after re-authentication.")
                    return None
            except Exception as ex:
                _LOGGER.error(
                    "Failed to get schedule: %s",
                    ex, exc_info=_z_tracebackiem(),
                )
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_dzd(self, date_from: str, date_to: str):
        """Pobierz zajęcia dodatkowe (DZD) z gateway API.

        Osobny endpoint /gateway/api/2.0/Timetables/OtherActivitiesRegister,
        którego biblioteka librus-apix nie zna. Autoryzacja jak w
        get_gateway_attendance: świeży oauth, potem client.get. Best-effort —
        przy dowolnym błędzie zwraca [] (plan pokaże się bez DZD).
        """
        try:
            if not self._client or not self._token:
                if not await self.async_authenticate():
                    return []
            client = self._client
            loop = asyncio.get_running_loop()

            def _fetch():
                _ensure_oauth(client)
                url = (
                    "%s/gateway/api/2.0/Timetables/OtherActivitiesRegister"
                    "?dateFrom=%s&dateTo=%s&hideOutdatedEntries=false"
                    % (client.BASE_URL, date_from, date_to)
                )
                resp = client.get(url)
                if resp.status_code == 401:
                    _ensure_oauth(client, force_refresh=True)
                    resp = client.get(url)
                payload = resp.json() or {}
                data = payload.get("data")
                if data is None:
                    _LOGGER.warning(
                        "DZD: brak pola 'data' (HTTP %s): %s",
                        getattr(resp, "status_code", "?"), str(payload)[:200],
                    )
                    return []
                return data

            return await loop.run_in_executor(None, _fetch)
        except Exception as dzd_ex:
            _LOGGER.warning("DZD: nie udało się pobrać zajęć dodatkowych: %s", dzd_ex)
            return []

    async def async_get_zsk(self, date_from: str, date_to: str):
        """Pobierz ZŚK i Nauczanie Indywidualne."""
        try:
            if not self._client or not self._token:
                if not await self.async_authenticate():
                    return []
            client = self._client
            loop = asyncio.get_running_loop()

            def _fetch():
                _ensure_oauth(client)

                results = []
                for endpoint in ["IndividualLearningPath", "OneToOneLearningPlan"]:
                    url = (
                        "%s/gateway/api/2.0/Timetables/%s"
                        "?dateFrom=%s&dateTo=%s&hideOutdatedEntries=false"
                        % (client.BASE_URL, endpoint, date_from, date_to)
                    )
                    resp = client.get(url)
                    if resp.status_code == 401:
                        _ensure_oauth(client, force_refresh=True)
                        resp = client.get(url)
                    payload = resp.json() or {}
                    data = payload.get("data")
                    if data is None:
                        _LOGGER.warning(
                            "ZŚK: brak pola 'data' dla %s (HTTP %s): %s",
                            endpoint,
                            getattr(resp, "status_code", "?"),
                            str(payload)[:200],
                        )
                        continue
                    results.extend(data)
                return results

            return await loop.run_in_executor(None, _fetch)
        except Exception as ex:
            _LOGGER.warning("ZŚK: nie udało się pobrać: %s", ex)
            return []

    async def async_get_notices(self):
        """Pobierz uwagi o zachowaniu z gateway API."""
        try:
            if not self._client or not self._token:
                if not await self.async_authenticate():
                    return []
            client = self._client
            loop = asyncio.get_running_loop()

            def _fetch():
                _ensure_oauth(client)
                resp = client.get(f"{client.BASE_URL}/gateway/api/2.0/Notices")
                if resp.status_code == 401:
                    _ensure_oauth(client, force_refresh=True)
                    resp = client.get(f"{client.BASE_URL}/gateway/api/2.0/Notices")
                payload = resp.json() or {}
                data = payload.get("Notices", [])
                
                # Czasem zalezy to od API, spróbujmy tez innej sciezki:
                if not data and "data" in payload:
                    data = payload.get("data", [])
                    
                result = []
                for notice in data:
                    cat = notice.get("Category", {})
                    teacher = notice.get("Teacher", {})
                    
                    result.append({
                        "data": notice.get("CreationDate", "")[:10],
                        "nauczyciel": f"{teacher.get('FirstName', '')} {teacher.get('LastName', '')}".strip(),
                        "kategoria": cat.get("Name", "Uwaga"),
                        "tresc": notice.get("Content", ""),
                        "typ": cat.get("Type", "Neutral") # Możliwe wartosci: Positive, Negative, Neutral
                    })
                return result

            return await loop.run_in_executor(None, _fetch)
        except Exception as ex:
            _LOGGER.warning("Uwagi: nie udało się pobrać uwag: %s", ex)
            return []

    async def async_get_timetable(self):
        """Get timetable (plan lekcji) from Librus."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None
                client = self._client

                from librus_apix.timetable import get_timetable
                from datetime import date as _date, datetime, timedelta

                today = _date.today()
                monday = today - timedelta(days=today.weekday())
                next_monday = monday + timedelta(days=7)

                loop = asyncio.get_running_loop()
                
                def _fetch_two_weeks():
                    tt1 = get_timetable(client, datetime.combine(monday, datetime.min.time()))
                    tt2 = get_timetable(client, datetime.combine(next_monday, datetime.min.time()))
                    return tt1 + tt2

                # LOCAL PATCH (DZD): zajęcia dodatkowe idą osobnym gateway-endpointem
                # (async_get_dzd). Sekwencyjnie po planie — obie funkcje dzielą tę samą
                # sesję requests klienta, więc nie wolno ich puścić równolegle.
                timetable = await loop.run_in_executor(None, _fetch_two_weeks)
                d_from = monday.strftime("%Y-%m-%d")
                d_to = (next_monday + timedelta(days=6)).strftime("%Y-%m-%d")
                dzd_events = await self.async_get_dzd(d_from, d_to)
                zsk_events = await self.async_get_zsk(d_from, d_to)

                result = []
                hour_to_num = {}
                dni_nazwy = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]
                
                # We have 14 days starting from 'monday'
                # We want 7 days starting from 'today'
                # 'today' is at index 'today.weekday()'
                start_idx = today.weekday()
                
                for i in range(start_idx, start_idx + 7):
                    day = timetable[i]
                    day_date = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
                    dzien_tyg = dni_nazwy[i % 7]
                    
                    day_list = []
                    for period in day:
                        if period.subject:
                            subject = period.subject
                            teacher_and_classroom = period.teacher_and_classroom

                            if "-" in subject:
                                suffix_that_got_prepended = "-".join(subject.split("-")[1:])
                                if teacher_and_classroom.startswith(suffix_that_got_prepended + "-"):
                                    teacher_and_classroom = teacher_and_classroom[len(suffix_that_got_prepended) + 1:]


                            odwolana = False
                            zastepstwo = False
                            if period.info:
                                for info_key, info_val in period.info.items():
                                    k_low = info_key.lower()
                                    if k_low in ("o", "n", "p") or "odwołane" in k_low or "okienko" in k_low or "zajęcia odwołane" in k_low or "przesunię" in k_low or "nieobecność" in k_low:
                                        odwolana = True
                                    if k_low == "z" or "zastępstwo" in k_low:
                                        zastepstwo = True

                                    if isinstance(info_val, dict):
                                        subject = subject.strip().replace("\n", " ")
                                        teacher_and_classroom = teacher_and_classroom.strip()

                                        subject_swap = info_val.get("subject_swap", "").strip()
                                        old_subject = subject_swap.split("->")[0].strip() if "->" in subject_swap else subject_swap
                                        if old_subject and old_subject.lower() != subject.lower():
                                            subject = f"{old_subject} ➔ {subject}"
                                        
                                        teacher_swap = info_val.get("teacher_swap", "").strip()
                                        classroom_swap = info_val.get("classroom_swap", "").strip()
                                        
                                        tc_parts = teacher_and_classroom.rsplit("-", 1)
                                        curr_teacher = tc_parts[0].strip()
                                        curr_room = tc_parts[1].strip() if len(tc_parts) > 1 else ""
                                        
                                        new_teacher = curr_teacher
                                        if teacher_swap:
                                            old_teacher = teacher_swap.split("->")[0].strip() if "->" in teacher_swap else teacher_swap
                                            if old_teacher and not curr_teacher.startswith(old_teacher):
                                                new_teacher = f"({old_teacher} ➔ {curr_teacher})"
                                                
                                        new_room = curr_room
                                        if classroom_swap:
                                            old_room = classroom_swap.split("->")[0].strip() if "->" in classroom_swap else classroom_swap
                                            if old_room and old_room != curr_room:
                                                if not curr_room or curr_room == "[brak]":
                                                    new_room = f"({old_room} ➔ brak)"
                                                else:
                                                    new_room = f"({old_room} ➔ {curr_room})"
                                                
                                        if new_teacher and new_room:
                                            teacher_and_classroom = f"{new_teacher} - {new_room}"
                                        elif new_teacher:
                                            teacher_and_classroom = new_teacher
                                        elif new_room:
                                            teacher_and_classroom = f"Sala {new_room}"
                                        break

                            nauczyciel = teacher_and_classroom
                            sala = ""
                            tc_lower = teacher_and_classroom.lower()
                            if " s. " in tc_lower:
                                idx = tc_lower.rfind(" s. ")
                                nauczyciel = teacher_and_classroom[:idx].strip()
                                sala = teacher_and_classroom[idx + 1:].strip()
                            elif " sala " in tc_lower:
                                idx = tc_lower.rfind(" sala ")
                                nauczyciel = teacher_and_classroom[:idx].strip()
                                sala = teacher_and_classroom[idx + 1:].strip()
                            elif " - " in teacher_and_classroom:
                                parts = teacher_and_classroom.rsplit(" - ", 1)
                                nauczyciel = parts[0].strip()
                                sala = parts[1].strip()

                            lekcja_dict = {
                                "przedmiot": subject,
                                "nauczyciel_i_sala": teacher_and_classroom,
                                "godzina_od": period.date_from,
                                "godzina_do": period.date_to,
                                "data": period.date or day_date,
                                "numer": period.number,
                                "zdarzenie": None,
                            }
                            # Zawsze te same klucze - szablony kart (tryb scisly) nie moga
                            # trafiac na brakujace pole, np. l.sala
                            lekcja_dict["odwolana"] = bool(odwolana)
                            lekcja_dict["zastepstwo"] = bool(zastepstwo)
                            lekcja_dict["nauczyciel"] = nauczyciel or ""
                            lekcja_dict["sala"] = sala or ""
                            day_list.append(lekcja_dict)
                            if period.date_from and period.number is not None:
                                hour_to_num.setdefault(period.date_from, period.number)
                    result.append({
                        "dzien_tygodnia": dzien_tyg,
                        "data": day_date,
                        "lekcje": day_list
                    })

                # LOCAL PATCH: wlej DZD oraz ZŚK do właściwych dni po dacie.
                by_date = {_d["data"]: _d for _d in result}
                touched = set()

                if dzd_events:
                    for ev in dzd_events:
                        try:
                            if str(ev.get("status", "")).upper().startswith("CANCEL"):
                                continue
                            _d = by_date.get(ev.get("date"))
                            if _d is None:
                                continue
                            start = (ev.get("startTime") or "")[:5]
                            end = (ev.get("endTime") or "")[:5]
                            room = ev.get("classroom") or {}
                            sala = room.get("name") or room.get("symbol") or ""
                            teacher = ev.get("teacherName") or ""
                            nis = ("%s  s. %s" % (teacher, sala)).strip() if sala else teacher
                            lekcje = _d.setdefault("lekcje", [])
                            title = ev.get("title") or "Zajęcia dodatkowe"
                            if any(x.get("godzina_od") == start and x.get("przedmiot") == title for x in lekcje):
                                continue
                            lekcje.append({
                                "przedmiot": title,
                                "nauczyciel_i_sala": nis,
                                "nauczyciel": teacher,
                                "sala": sala,
                                "godzina_od": start,
                                "godzina_do": end,
                                "data": ev.get("date"),
                                "numer": hour_to_num.get(start),
                                "dzd": True,
                                "odwolana": False,
                                "zastepstwo": False,
                                "zdarzenie": None,
                            })
                            touched.add(ev.get("date"))
                        except Exception as merge_ex:
                            _LOGGER.debug("DZD: pominięto wpis: %s", merge_ex)

                if zsk_events:
                    for ev in zsk_events:
                        try:
                            _d = by_date.get(ev.get("date"))
                            if _d is None:
                                continue
                            start = (ev.get("startTime") or "")[:5]
                            end = (ev.get("endTime") or "")[:5]
                            room = ev.get("classroom") or {}
                            sala = room.get("symbol") or room.get("name") or ""
                            teacher = ev.get("teacherName") or ""
                            nis = ("%s  s. %s" % (teacher, sala)).strip() if sala else teacher
                            lekcje = _d.setdefault("lekcje", [])
                            title = ev.get("subject") or ev.get("title") or "ZŚK"
                            is_canceled = str(ev.get("status", "")).upper().startswith("CANCEL")
                            if any(x.get("godzina_od") == start and title in x.get("przedmiot", "") for x in lekcje):
                                continue

                            lekcje.append({
                                "przedmiot": f"{title} [ZŚK]",
                                "nauczyciel_i_sala": nis,
                                "nauczyciel": teacher,
                                "sala": sala,
                                "godzina_od": start,
                                "godzina_do": end,
                                "data": ev.get("date"),
                                "numer": hour_to_num.get(start),
                                "dzd": False,
                                "zsk": True,
                                "odwolana": is_canceled,
                                "zastepstwo": False,
                                "zdarzenie": None,
                            })
                            touched.add(ev.get("date"))
                        except Exception as merge_ex:
                            _LOGGER.debug("ZŚK: pominięto wpis: %s", merge_ex)

                for dt in touched:
                    by_date[dt]["lekcje"].sort(key=lambda x: (x.get("godzina_od") or "99:99"))

                return result

            except TokenError:
                _LOGGER.debug(
                    "Token expired fetching timetable (attempt %d/2), re-authenticating...",
                    attempt + 1,
                )
                self._reset_auth()
                if attempt == 1:
                    _LOGGER.error("Failed to get timetable after re-authentication.")
                    return None
            except Exception as ex:
                if type(ex).__name__ == "ParseError":
                    _LOGGER.info("Brak planu lekcji w tym tygodniu (wakacje/brak danych). Zwracam pusty plan.")
                    return []
                _LOGGER.error(
                    "Failed to get timetable: %s",
                    ex, exc_info=_z_tracebackiem(),
                )
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_student_information(self):
        """Get student information from Librus."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None

                from librus_apix.student_information import get_student_information

                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, get_student_information, self._client)

            except TokenError:
                _LOGGER.debug(
                    "Token expired fetching student information (attempt %d/2), re-authenticating...",
                    attempt + 1,
                )
                self._reset_auth()
                if attempt == 1:
                    _LOGGER.error("Failed to get student information after re-authentication.")
                    return None
            except Exception as ex:
                _LOGGER.error(
                    "Failed to get student information: %s",
                    ex, exc_info=_z_tracebackiem(),
                )
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_attendance(self):
        """Get attendance from Librus."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None

                from librus_apix.attendance import get_attendance
                loop = asyncio.get_running_loop()
                attendance = await loop.run_in_executor(None, get_attendance, self._client)
                
                result = []
                if attendance:
                    for sem in attendance:
                        for a in sem:
                            result.append({
                                "symbol": getattr(a, "symbol", ""),
                                "typ": getattr(a, "type", ""),
                                "data": getattr(a, "date", ""),
                                "przedmiot": getattr(a, "subject", ""),
                                "nauczyciel": getattr(a, "teacher", ""),
                                "godzina": getattr(a, "period", 0)
                            })
                return result
            except TokenError:
                _LOGGER.debug("Token expired fetching attendance (attempt %d/2), re-authenticating...", attempt + 1)
                self._reset_auth()
                if attempt == 1:
                    return None
            except Exception as ex:
                if type(ex).__name__ == "ParseError":
                    return []
                _LOGGER.error("Failed to get attendance: %s", ex)
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_announcements(self):
        """Get announcements from Librus."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None

                from librus_apix.announcements import get_announcements
                loop = asyncio.get_running_loop()
                ann = await loop.run_in_executor(None, get_announcements, self._client)
                
                result = []
                if ann:
                    for a in ann:
                        result.append({
                            "tytul": getattr(a, "title", ""),
                            "nadawca": getattr(a, "author", ""),
                            "opis": getattr(a, "description", ""),
                            "data": getattr(a, "date", "")
                        })
                return result
            except TokenError:
                _LOGGER.debug("Token expired fetching announcements (attempt %d/2), re-authenticating...", attempt + 1)
                self._reset_auth()
                if attempt == 1:
                    return None
            except Exception as ex:
                if type(ex).__name__ == "ParseError":
                    return []
                _LOGGER.error("Failed to get announcements: %s", ex)
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_completed_lessons(self, days: int = 7):
        """Pobierz zrealizowane lekcje (tematy) z ostatnich `days` dni.

        Strona "Zrealizowane lekcje" jest stronicowana po 15 wpisow. Pobieramy
        wszystkie strony z zakresu (max 10) i usuwamy duplikaty - Librus
        przy numerze strony poza zakresem zwraca ostatnia strone.

        Wiersze parsujemy sami (_parse_completed_lessons), bo
        librus_apix.completed_lessons zaklada stala liczbe kolumn, a czesc
        szkol ma dodatkowa kolumne "e-Tablica" - wtedy biblioteka zwraca
        pusta frekwencje zamiast "ob"/"nb".
        """
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None
                client = self._client

                from datetime import date as _date, timedelta

                today = _date.today()
                date_from = (today - timedelta(days=days)).strftime("%Y-%m-%d")
                date_to = today.strftime("%Y-%m-%d")

                def _fetch_all_pages():
                    last_post = {}
                    orig_post = client.post
                    def _caching_post(url, data=None, **kwargs):
                        if url == client.COMPLETED_LESSONS_URL and data and data.get("numer_strony1001") == 0:
                            if "page_0" in last_post:
                                return last_post["page_0"]
                            resp = orig_post(url, data=data, **kwargs)
                            last_post["page_0"] = resp
                            return resp
                        return orig_post(url, data=data, **kwargs)

                    try:
                        client.post = _caching_post
                        from librus_apix.completed_lessons import get_max_page_number
                        try:
                            max_pages = get_max_page_number(client, date_from, date_to)
                        except Exception:
                            max_pages = 0

                        lessons = []
                        seen = set()
                        for page in range(min(max_pages, 9) + 1):
                            resp = client.post(
                                client.COMPLETED_LESSONS_URL,
                                data={
                                    "data1": date_from,
                                    "data2": date_to,
                                    "filtruj_id_przedmiotu": -1,
                                    "numer_strony1001": page,
                                    "porcjowanie_pojemnik1001": 1001,
                                },
                            )
                            html = resp.text if hasattr(resp, "text") else str(resp)
                            for lesson in _parse_completed_lessons(html):
                                key = (lesson["data"], lesson["numer"], lesson["przedmiot"], lesson["temat"])
                                if key in seen:
                                    continue
                                seen.add(key)
                                lessons.append(lesson)
                        return lessons
                    finally:
                        client.post = orig_post

                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, _fetch_all_pages)
                # Najnowszy dzien na poczatku, w obrebie dnia wg numeru lekcji
                result.sort(key=lambda l: (l["numer"] if l["numer"] is not None else 99))
                result.sort(key=lambda l: l["data"], reverse=True)
                return result

            except TokenError:
                _LOGGER.debug(
                    "Token expired fetching completed lessons (attempt %d/2), re-authenticating...",
                    attempt + 1,
                )
                self._reset_auth()
                if attempt == 1:
                    return None
            except Exception as ex:
                if type(ex).__name__ == "ParseError":
                    return []
                _LOGGER.error(
                    "Failed to get completed lessons: %s",
                    ex, exc_info=_z_tracebackiem(),
                )
                # Bez ponawiania: blad nie wynika z wygaslego tokena,
                # druga proba tylko zdublowalaby zapytania. Ponowi nastepny cykl.
                return None

    async def async_get_attendance_stats(self):
        """Pobierz wszystkie wpisy frekwencji (takze obecnosci) z gateway API.

        Potrzebne do wyliczenia procentu frekwencji - strona HTML pokazuje
        tylko nieobecnosci/spoznienia. Best-effort: przy bledzie zwraca None
        (czujnik pokaze wtedy dane bez procentu).
        Zwraca liste (symbol, semestr), np. ("ob", 1).
        """
        types = {
            "1": "nb",
            "2": "sp",
            "3": "u",
            "4": "zw",
            "100": "ob",
            "1266": "wy",
            "2022": "k",
            "2829": "sz",
        }
        try:
            if not self._client or not self._token:
                if not await self.async_authenticate():
                    return None
            client = self._client
            loop = asyncio.get_running_loop()

            def _fetch():
                _ensure_oauth(client)
                resp = client.get(client.GATEWAY_API_ATTENDANCE)
                if resp.status_code == 401:
                    _ensure_oauth(client, force_refresh=True)
                    resp = client.get(client.GATEWAY_API_ATTENDANCE)
                payload = resp.json() or {}
                attendances = payload.get("Attendances")
                if attendances is None:
                    _LOGGER.warning(
                        "Frekwencja: brak pola 'Attendances' (HTTP %s): %s",
                        getattr(resp, "status_code", "?"), str(payload)[:200],
                    )
                    return None
                result = []
                for a in attendances:
                    type_id = str((a.get("Type") or {}).get("Id", ""))
                    result.append((types.get(type_id, "inne"), a.get("Semester")))
                return result

            return await loop.run_in_executor(None, _fetch)
        except Exception as ex:
            _LOGGER.warning("Frekwencja: nie udało się pobrać statystyk: %s", ex)
            return None

    async def async_get_notes(self):
        """Pobierz uwagi z gateway API (Notes, Notes/Categories, Users).

        Best-effort: przy bledzie zwraca None (czujnik zostawi poprzednie dane).
        Zwraca liste uwag od najnowszej.
        """
        try:
            if not self._client or not self._token:
                if not await self.async_authenticate():
                    return None
            client = self._client
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, _fetch_notes, client)
        except Exception as ex:
            _LOGGER.warning("Uwagi: nie udało się pobrać: %s", ex)
            return None


_RODZAJ_UWAGI = {0: "negatywna", 1: "pozytywna", 2: "neutralna"}


def _fetch_notes(client) -> list | None:
    """Pobierz i zmapuj uwagi (wywolywane w executorze)."""
    _ensure_oauth(client)
    api = client.BASE_URL + "/gateway/api/2.0/"
    resp = client.get(api + "Notes")
    if resp.status_code == 401:
        _ensure_oauth(client, force_refresh=True)
        resp = client.get(api + "Notes")
    payload = resp.json() or {}
    notes = payload.get("Notes")
    if notes is None:
        _LOGGER.warning("Uwagi: brak pola 'Notes': %s", str(payload)[:200])
        return None
    if not notes:
        return []
    kategorie = getattr(client, "_notice_categories_cache", None)
    if not isinstance(kategorie, dict):
        try:
            kategorie = {
                c["Id"]: c.get("CategoryName", "")
                for c in client.get(api + "Notes/Categories").json().get("Categories", [])
            }
            client._notice_categories_cache = kategorie
        except Exception as ex:  # bez kategorii tez sie da
            _LOGGER.debug("Nie udało się pobrać kategorii uwag: %s", ex)
            kategorie = {}
    osoby = getattr(client, "_notice_users_cache", None)
    if not isinstance(osoby, dict):
        try:
            users = client.get(api + "Users").json().get("Users", [])
            osoby = {u["Id"]: f"{u.get('LastName', '')} {u.get('FirstName', '')}".strip() for u in users}
            client._notice_users_cache = osoby
        except Exception as ex:
            _LOGGER.debug("Nie udało się pobrać użytkowników dla uwag: %s", ex)
            osoby = {}
    return _map_notes(notes, kategorie, osoby)


def _map_notes(notes: list, kategorie: dict, osoby: dict) -> list:
    """Zamien surowe uwagi z API na liste slownikow (od najnowszej)."""
    result = []
    for n in notes:
        positive = n.get("Positive")
        result.append({
            "id": n.get("Id"),
            "data": (n.get("Date") or "")[:10],
            "tresc": (n.get("Text") or "").strip(),
            "rodzaj": _RODZAJ_UWAGI.get(positive, "inna"),
            "kategoria": kategorie.get((n.get("Category") or {}).get("Id"), ""),
            "nauczyciel": osoby.get((n.get("Teacher") or {}).get("Id"), ""),
        })
    return sorted(result, key=lambda u: (u["data"], u["id"] or 0), reverse=True)


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up the Librus APIX component."""
    hass.data.setdefault(DOMAIN, {})
    
    if DOMAIN in config:
        username = config[DOMAIN][CONF_USERNAME]
        password = config[DOMAIN][CONF_PASSWORD]
        
        client = LibrusApiClient(username, password)
        hass.data[DOMAIN]["client"] = client
        
        # Test authentication
        if not await client.async_authenticate():
            _LOGGER.error("Failed to authenticate")
            return False

    def _is_librus_client(obj) -> bool:
        return (
            isinstance(obj, LibrusApiClient)
            or getattr(obj, "__class__", None).__name__ == "LibrusApiClient"
            or hasattr(obj, "async_get_messages")
        )

    async def handle_get_message(call):
        """Obsluga wywolania pobierania wiadomosci."""
        url = call.data.get("url")
        if not url:
            _LOGGER.error("Brak URL wiadomosci")
            return {"content": None, "error": "Brak URL wiadomosci"}

        entity_id = call.data.get("entity_id")
        client = None

        # 1. Jesli podano jawne entity_id (np. sensor wiadomosci danego ucznia)
        if entity_id:
            try:
                from homeassistant.helpers import entity_registry as er
                ent_reg = er.async_get(hass)
                reg_entry = ent_reg.async_get(entity_id)
                cfg_id = getattr(reg_entry, "config_entry_id", None)
                if cfg_id:
                    candidate = hass.data.get(DOMAIN, {}).get(cfg_id)
                    if _is_librus_client(candidate):
                        client = candidate
            except Exception as ex:
                _LOGGER.debug("Nie udalo sie dopasowac klienta po entity_id %s: %s", entity_id, ex)

        # 2. Jesli nie wskazano klienta jawnie, sprobuj dopasowac ucznia po URL wiadomosci
        if not client:
            for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
                if _is_librus_client(entry_data):
                    # Sprawdz czy URL jest w cache wiadomosci tego klienta
                    if url in getattr(entry_data, "_message_cache", {}):
                        client = entry_data
                        break
                    # Lub w pobranych danych koordynatora
                    coord = getattr(entry_data, "coordinator", None)
                    if coord and getattr(coord, "data", None):
                        msgs = coord.data.get("wiadomosci", [])
                        if any(isinstance(m, dict) and m.get("href") == url for m in msgs):
                            client = entry_data
                            break

        # 3. Fallback: wez pierwszego zarejestrowanego klienta (np. pojedynczy uczen lub archiwalny URL)
        if not client:
            for entry_id, entry_data in hass.data.get(DOMAIN, {}).items():
                if _is_librus_client(entry_data):
                    client = entry_data
                    break

        if not client:
            _LOGGER.error("Brak skonfigurowanego klienta Librus")
            return {"content": None, "error": "Brak skonfigurowanego klienta Librus"}

        if not client._client or not client._token:
            if not await client.async_authenticate():
                _LOGGER.error("Nie udalo sie uwierzytelnic")
                return {"content": None, "error": "Nie udalo sie uwierzytelnic klienta"}

        try:
            from librus_apix.messages import message_content
            from contextlib import nullcontext
            import asyncio
            loop = asyncio.get_running_loop()
            lock = getattr(client, "_session_lock", None) or nullcontext()
            async with lock:
                msg_data = await loop.run_in_executor(None, message_content, client._client, url)

            content_str = msg_data.content if hasattr(msg_data, 'content') else str(msg_data)
            _LOGGER.info("Pobrano wiadomosc z %s", url)

            # Fire event to let user know message was read
            hass.bus.async_fire(
                f"{DOMAIN}_message_read",
                {"url": url, "content": content_str}
            )

            return {"content": content_str}
        except Exception as ex:
            _LOGGER.error("Blad pobierania wiadomosci %s: %s", url, ex)
            return {"content": None, "error": str(ex)}

    hass.services.async_register(
        DOMAIN,
        "get_message",
        handle_get_message,
        supports_response=SupportsResponse.OPTIONAL,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Librus APIX from a config entry."""
    try:
        import soupsieve  # juz zaladowany przy imporcie integracji - bez blokowania
        ss_ver = str(getattr(soupsieve, "__version__", ""))
        if ss_ver in ("3.0", "3.0.0"):
            _LOGGER.error(
                "Wykryto wadliwą wersję biblioteki soupsieve (%s). Powoduje ona brak ocen (Issue #39). "
                "Zaktualizuj bibliotekę soupsieve do wersji 3.0.1+ lub przeładuj zależności integracji.",
                ss_ver,
            )
    except Exception as ss_ex:
        _LOGGER.debug("Nie udało się sprawdzić wersji soupsieve: %s", ss_ex)

    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    options = entry.options
    
    client = LibrusApiClient(username, password, options, hass=hass)
    
    await client.async_init_cache()
    
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    coordinator = LibrusDataUpdateCoordinator(hass, client)
    client.coordinator = coordinator
    await coordinator.async_init_study_store(entry.entry_id)

    # Spróbuj załadować cache całego stanu z dysku dla natychmiastowego startu
    cached_data = await coordinator.async_load_cached_data()
    if cached_data:
        coordinator.seed_seen_from_cached_data(cached_data)
        coordinator.async_set_updated_data(cached_data)
        wiek = coordinator.wiek_cache()
        # update_interval moze byc None (odpytywanie wylaczone) - wtedy 0,
        # czyli odswiezenie od razu jak przed zmiana.
        interwal = coordinator.update_interval.total_seconds() if coordinator.update_interval else 0
        if wiek is not None and 0 <= wiek < interwal:
            # Dane sa swieze (np. szybki restart HA) - bez zapytan do Librusa
            # przy starcie, odswiezenie dopiero gdy minie interwal od pobrania.
            _LOGGER.debug(
                "Cache %s sprzed %d s - pierwsze odświeżenie za %d s",
                username, int(wiek), int(interwal - wiek),
            )

            async def _odswiez_po_starcie(_now) -> None:
                await coordinator.async_refresh()

            entry.async_on_unload(
                async_call_later(hass, interwal - wiek, _odswiez_po_starcie)
            )
        else:
            entry.async_create_background_task(
                hass,
                coordinator.async_refresh(),
                name=f"{DOMAIN}_{entry.entry_id}_startup_refresh",
            )
    else:
        # Pierwsze uruchomienie bez cache - autoryzacja i pełne pobranie
        if not await client.async_authenticate():
            _LOGGER.error("Failed to authenticate")
            return False
        await coordinator.async_config_entry_first_refresh()
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = client
    
    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    client = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if client and getattr(client, "_bg_fetch_task", None) and not client._bg_fetch_task.done():
        client._bg_fetch_task.cancel()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)