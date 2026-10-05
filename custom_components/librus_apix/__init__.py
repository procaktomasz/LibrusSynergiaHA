"""The Librus APIX integration."""

import asyncio
import logging
import traceback
from datetime import date
from typing import Dict, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv

from librus_apix.client import Client, new_client
from librus_apix.exceptions import TokenError

from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


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


PLATFORMS = ["sensor", "calendar", "todo", "button"]

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

    def __init__(self, username: str, password: str, options: dict = None):
        """Initialize the client."""
        self.username = username
        self.password = password
        self.options = options or {}
        self._client: Client = None
        self._token = None
        self._auth_lock = asyncio.Lock()

    def _reset_auth(self) -> None:
        """Reset authentication state to force re-authentication on next call."""
        self._client = None
        self._token = None

    async def async_authenticate(self):
        """Authenticate with Librus API."""
        async with self._auth_lock:
            try:
                loop = asyncio.get_running_loop()
                self._client = await loop.run_in_executor(None, new_client)
                self._token = await loop.run_in_executor(
                    None, self._client.get_token, self.username, self.password
                )
                _LOGGER.debug("Authentication successful for %s", self.username)
                return True
            except Exception as ex:
                _LOGGER.error("Authentication failed: %s\n%s", ex, traceback.format_exc())
                self._reset_auth()
                return False

    async def async_get_grades(self):
        """Get grades from Librus."""
        for attempt in range(2):
            try:
                if not self._client or not self._token:
                    if not await self.async_authenticate():
                        return None
                client = self._client

                from librus_apix.grades import get_grades

                loop = asyncio.get_running_loop()
                numeric_grades, average_grades, descriptive_grades = await loop.run_in_executor(
                    None, get_grades, client, "all"
                )

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
                                    'type': 'descriptive'
                                })

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
                _LOGGER.error(
                    "Failed to get grades (attempt %d/2): %s\n%s",
                    attempt + 1, ex, traceback.format_exc(),
                )
                self._reset_auth()
                if attempt == 1:
                    return None

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
                messages = await loop.run_in_executor(None, get_received, client, 0)
                messages = messages[:count] if messages else []
                
                fetch_content = self.options.get("fetch_messages_content", False)

                result = []
                for msg in messages:
                    msg_dict = {
                        "author": msg.author,
                        "title": msg.title,
                        "date": msg.date,
                        "href": msg.href,
                        "unread": msg.unread,
                        "has_attachment": msg.has_attachment,
                    }
                    if fetch_content:
                        try:
                            msg_data = await loop.run_in_executor(None, message_content, client, msg.href)
                            content_str = msg_data.content if hasattr(msg_data, 'content') else str(msg_data)
                            msg_dict["content"] = content_str.replace("\n", "<br>") if isinstance(content_str, str) else content_str
                        except Exception as e:
                            _LOGGER.warning("Could not fetch content for message %s: %s", msg.href, e)
                            msg_dict["content"] = None
                    
                    result.append(msg_dict)

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
                    "Failed to get messages (attempt %d/2): %s\n%s",
                    attempt + 1, ex, traceback.format_exc(),
                )
                self._reset_auth()
                if attempt == 1:
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
                    "Failed to get homework (attempt %d/2): %s\n%s",
                    attempt + 1, ex, traceback.format_exc(),
                )
                self._reset_auth()
                if attempt == 1:
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
                                    "przedmiot": ev.subject,
                                    "godzina": ev.hour,
                                    "numer_lekcji": ev.number,
                                    "szczegoly": szczegoly,
                                    "href": ev.href,
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
                    "Failed to get schedule (attempt %d/2): %s\n%s",
                    attempt + 1, ex, traceback.format_exc(),
                )
                self._reset_auth()
                if attempt == 1:
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
                oauth = client.refresh_oauth()
                if oauth:
                    client.cookies["oauth_token"] = oauth
                url = (
                    "%s/gateway/api/2.0/Timetables/OtherActivitiesRegister"
                    "?dateFrom=%s&dateTo=%s&hideOutdatedEntries=false"
                    % (client.BASE_URL, date_from, date_to)
                )
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
                oauth = client.refresh_oauth()
                if oauth:
                    client.cookies["oauth_token"] = oauth

                results = []
                for endpoint in ["IndividualLearningPath", "OneToOneLearningPlan"]:
                    url = (
                        "%s/gateway/api/2.0/Timetables/%s"
                        "?dateFrom=%s&dateTo=%s&hideOutdatedEntries=false"
                        % (client.BASE_URL, endpoint, date_from, date_to)
                    )
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
                            if odwolana:
                                lekcja_dict["odwolana"] = True
                            if zastepstwo:
                                lekcja_dict["zastepstwo"] = True
                            if nauczyciel:
                                lekcja_dict["nauczyciel"] = nauczyciel
                            if sala:
                                lekcja_dict["sala"] = sala
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
                    "Failed to get timetable (attempt %d/2): %s\n%s",
                    attempt + 1, ex, traceback.format_exc(),
                )
                self._reset_auth()
                if attempt == 1:
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
                    "Failed to get student information (attempt %d/2): %s\n%s",
                    attempt + 1, ex, traceback.format_exc(),
                )
                self._reset_auth()
                if attempt == 1:
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
                _LOGGER.error("Failed to get attendance (attempt %d/2): %s", attempt + 1, ex)
                self._reset_auth()
                if attempt == 1:
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
                _LOGGER.error("Failed to get announcements (attempt %d/2): %s", attempt + 1, ex)
                self._reset_auth()
                if attempt == 1:
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

                from librus_apix.completed_lessons import get_max_page_number
                from datetime import date as _date, timedelta

                today = _date.today()
                date_from = (today - timedelta(days=days)).strftime("%Y-%m-%d")
                date_to = today.strftime("%Y-%m-%d")

                def _fetch_all_pages():
                    max_pages = get_max_page_number(client, date_from, date_to)
                    lessons = []
                    seen = set()
                    for page in range(min(max_pages, 9) + 1):
                        html = client.post(
                            client.COMPLETED_LESSONS_URL,
                            data={
                                "data1": date_from,
                                "data2": date_to,
                                "filtruj_id_przedmiotu": -1,
                                "numer_strony1001": page,
                                "porcjowanie_pojemnik1001": 1001,
                            },
                        ).text
                        for lesson in _parse_completed_lessons(html):
                            key = (lesson["data"], lesson["numer"], lesson["przedmiot"], lesson["temat"])
                            if key in seen:
                                continue
                            seen.add(key)
                            lessons.append(lesson)
                    return lessons

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
                    "Failed to get completed lessons (attempt %d/2): %s\n%s",
                    attempt + 1, ex, traceback.format_exc(),
                )
                self._reset_auth()
                if attempt == 1:
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
                oauth = client.refresh_oauth()
                if oauth:
                    client.cookies["oauth_token"] = oauth
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

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Librus APIX from a config entry."""
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    options = entry.options
    
    client = LibrusApiClient(username, password, options)
    
    # Test authentication
    if not await client.async_authenticate():
        _LOGGER.error("Failed to authenticate")
        return False
    
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    from .sensor import LibrusDataUpdateCoordinator
    coordinator = LibrusDataUpdateCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()
    client.coordinator = coordinator
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = client
    
    # Setup platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)