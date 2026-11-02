"""Platforma czujników dla integracji Librus APIX."""

import asyncio
import copy
import json
import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.helpers.storage import Store

from .const import (
    CONF_POKAZUJ_NIELICZONE,
    CONF_SCAN_INTERVAL_OTHER,
    CONF_SCAN_INTERVAL_SCHOOL,
    DEFAULT_SCAN_INTERVAL_OTHER,
    DEFAULT_SCAN_INTERVAL_SCHOOL,
    DOMAIN,
    is_exam_event,
)

_LOGGER = logging.getLogger(__name__)


def _id_nieobecnosci(lekcja: Dict) -> tuple:
    """Identyfikator wpisu frekwencji przy lekcji (zmiana wpisu = nowy id)."""
    return (lekcja.get("data"), lekcja.get("numer"), lekcja.get("przedmiot"), lekcja.get("obecnosc"))


def _plan_bez_fuzji(plan: List[Dict]) -> List[Dict]:
    """Kopia planu bez wpisow dodanych przez fuzje z terminarzem.

    Plan z poprzedniego cyklu lub z cache jest juz scalony (zdarzenia przy
    lekcjach, sztuczne lekcje "??:??", dni wolne). Ponowna fuzja na takim
    planie dublowala wpisy i zostawiala zdarzenia usuniete z terminarza.
    """
    wynik = copy.deepcopy(plan or [])
    for dzien in wynik:
        if not isinstance(dzien, dict):
            continue
        dzien.pop("dzien_wolny", None)
        if "lekcje" in dzien:
            lekcje = [lk for lk in dzien["lekcje"] or [] if lk.get("godzina_od") != "??:??"]
            for lk in lekcje:
                lk["zdarzenie"] = None
                lk.pop("zdarzenie_opis", None)
            dzien["lekcje"] = lekcje
    return wynik


def _jest_nowa(date_str: str) -> bool:
    """Sprawdz czy data miesci sie w ostatnich 24 godzinach (dzis lub wczoraj)."""
    if not date_str:
        return False
    wczoraj = date.today() - timedelta(days=1)
    for fmt in (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d.%m.%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            d = datetime.strptime(date_str.strip(), fmt).date()
            return d >= wczoraj
        except ValueError:
            continue
    return False


def _podziel_oceny(oceny: List[Dict]) -> tuple:
    """Rozdziel oceny na skale 1-6 (z +/-, literowe) i wyniki procentowe/punktowe.

    Pomija oceny niewliczane do sredniej (liczona: false).
    """
    import re
    skala: List[float] = []
    procenty: List[float] = []

    literowe = {"A": 5.0, "B": 4.0, "C": 2.0, "D": 1.0, "E": 1.0, "F": 1.0}

    for g in oceny:
        if g.get("liczona") is False:
            continue
        grade_str = g.get("ocena", "").strip().rstrip("*")
        if not grade_str:
            continue

        # Ocena punktowa ze znana skala (np. 14 w skali 0-20) - liczymy procent
        if g.get("punktowa") and g.get("procent") is not None:
            procenty.append(float(g["procent"]))
            continue

        try:
            # 1. Sprawdz czy to czysta liczba wielocyfrowa lub z %/p/pkt (np. 95, 100, 95%, 85 pkt)
            if grade_str.isdigit() and len(grade_str) > 1:
                # Jesli dwu- lub trzycyfrowa, np. 95, bierzemy calosc jako punktacja
                procenty.append(float(grade_str))
                continue

            match = re.search(r'^(\d+)(?:\s*(?:%|p|pkt))?$', grade_str.lower())
            if match:
                val = float(match.group(1))
                if val > 6 or grade_str.lower().endswith(('%', 'p', 'pkt')):
                    procenty.append(val)
                    continue

            # 1b. Sprawdź format X/Y (np. 85/100)
            if "/" in grade_str:
                parts = grade_str.split("/")
                if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
                    num = float(parts[0].strip())
                    den = float(parts[1].strip())
                    if den == 100:
                        procenty.append(num)
                    else:
                        procenty.append(num / den * 100)
                    continue

            # 2. Sprawdz czy to ocena literowa (klasy 1-3)
            base_char = grade_str[0].upper()
            if base_char in literowe:
                base = literowe[base_char]
                if len(grade_str) > 1:
                    if "+" in grade_str:
                        base += 0.5
                    elif "-" in grade_str:
                        base -= 0.25
                skala.append(base)
                continue

            # 3. Standardowa logika Librusa 1-6
            base = float(grade_str[0])
            if len(grade_str) > 1:
                if "+" in grade_str:
                    base += 0.5
                elif "-" in grade_str:
                    base -= 0.25
            skala.append(base)
        except (ValueError, IndexError):
            continue
    return skala, procenty


def _srednia_ocen(oceny: List[Dict]) -> Optional[float]:
    """Srednia ocen (bez ocen niewliczanych do sredniej).

    Wyniki procentowe/punktowe nie mieszaja sie z ocenami 1-6 (#52): gdy sa
    oceny 1-6, srednia liczona jest tylko z nich. Gdy sa wylacznie wyniki
    procentowe, srednia jest z procentow - jak dotad.
    """
    skala, procenty = _podziel_oceny(oceny)
    wartosci = skala or procenty
    return round(sum(wartosci) / len(wartosci), 2) if wartosci else None


def _srednia_procent(oceny: List[Dict]) -> Optional[float]:
    """Srednia z wynikow procentowych/punktowych (None gdy ich brak)."""
    _, procenty = _podziel_oceny(oceny)
    return round(sum(procenty) / len(procenty), 2) if procenty else None


# Symbole liczone jako obecnosc (jak w librus_apix.attendance.get_attendance_frequency)
_OBECNOSC = ("ob", "sp", "wy")


def _frekwencja_statystyki(wpisy: List[tuple], semestr: int) -> Dict[str, Any]:
    """Policz frekwencje z listy (symbol, semestr) z gateway API.

    Zwraca procent obecnosci w biezacym semestrze i w calym roku oraz liczbe
    wpisow kazdego rodzaju w biezacym semestrze.
    """
    def _procent(lista):
        if not lista:
            return None
        obecne = sum(1 for s in lista if s in _OBECNOSC)
        return round(100 * obecne / len(lista), 1)

    w_semestrze = [s for s, sem in wpisy if sem == semestr]
    rodzaje: Dict[str, int] = {}
    for s in w_semestrze:
        rodzaje[s] = rodzaje.get(s, 0) + 1
    return {
        "procent_semestr": _procent(w_semestrze),
        "procent_rok": _procent([s for s, _ in wpisy]),
        "lekcji_w_semestrze": len(w_semestrze),
        "rodzaje": rodzaje,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy czujnikow Librus APIX."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = client.coordinator

    entities: List[SensorEntity] = [
        LibrusUczenSensor(coordinator, config_entry),
        LibrusSzczesliwyNumerekSensor(coordinator, config_entry),
        LibrusOcenySensor(coordinator, config_entry),
        LibrusWiadomosciSensor(coordinator, config_entry),
        LibrusZadaniaSensor(coordinator, config_entry),
        LibrusTerminarzSensor(coordinator, config_entry),
        LibrusPlanLekcjiSensor(coordinator, config_entry),
        LibrusFrekwencjaSensor(coordinator, config_entry),
        LibrusOgloszeniaSensor(coordinator, config_entry),
        LibrusTematyLekcjiSensor(coordinator, config_entry),
        LibrusUwagiSensor(coordinator, config_entry),
        LibrusZachowanieSensor(coordinator, config_entry),
    ]

    # Tworz czujniki per przedmiot na podstawie pierwszego pobrania danych
    for subject in coordinator.data.get("oceny_wg_przedmiotu", {}).keys():
        entities.append(LibrusPrzedmiotSensor(coordinator, subject, config_entry))
        entities.append(LibrusSredniaPrzedmiotuSensor(coordinator, subject, config_entry))

    # Czujnik globalnej sredniej
    entities.append(LibrusSredniaOcenSensor(coordinator, config_entry))

    # Opcjonalne: Czujniki AI
    if config_entry.options.get("ai_summary_enabled", False):
        entities.append(LibrusAISummarySensor(coordinator, config_entry, "rodzic"))
        entities.append(LibrusAISummarySensor(coordinator, config_entry, "uczen"))
        entities.append(LibrusAIMessagesSummarySensor(coordinator, config_entry, "rodzic"))
        entities.append(LibrusAIMessagesSummarySensor(coordinator, config_entry, "uczen"))

    async_add_entities(entities)


EVENT_NOWA_WIADOMOSC = f"{DOMAIN}_nowa_wiadomosc"
EVENT_NOWA_OCENA = f"{DOMAIN}_nowa_ocena"
EVENT_NOWE_ZADANIE = f"{DOMAIN}_nowe_zadanie"
EVENT_NOWE_ZDARZENIE = f"{DOMAIN}_nowe_zdarzenie"
EVENT_NOWA_NIEOBECNOSC = f"{DOMAIN}_nowa_nieobecnosc"

# Wpisy frekwencji oznaczajace obecnosc - nie wysylamy dla nich zdarzen
_BEZ_ZDARZENIA = ("", "ob", "wy")
EVENT_NOWA_UWAGA = f"{DOMAIN}_nowa_uwaga"


def _student_info_to_dict(info) -> Optional[Dict[str, Any]]:
    """Przekształć obiekt StudentInformation na słownik do serializacji JSON."""
    if not info:
        return None
    if isinstance(info, dict):
        return info
    return {
        "name": getattr(info, "name", ""),
        "class_name": getattr(info, "class_name", ""),
        "number": getattr(info, "number", 0),
        "tutor": getattr(info, "tutor", ""),
        "school": getattr(info, "school", ""),
        "lucky_number": getattr(info, "lucky_number", ""),
    }


def _zrzut_cache(data: Dict[str, Any]) -> Optional[str]:
    """Tekstowy odcisk stanu do porownania z ostatnim zapisem (None gdy sie nie da)."""
    try:
        return json.dumps(data, sort_keys=True, default=str)
    except Exception as ex:
        _LOGGER.debug("Nie udało się porównać stanu z cache: %s", ex)
        return None


def _student_info_from_dict(data: Optional[Dict[str, Any]]):
    """Odtwórz obiekt StudentInformation ze słownika."""
    if not data or not isinstance(data, dict):
        return None
    try:
        from librus_apix.student_information import StudentInformation
        return StudentInformation(
            data.get("name", ""),
            data.get("class_name", ""),
            data.get("number", 0),
            data.get("tutor", ""),
            data.get("school", ""),
            data.get("lucky_number", ""),
        )
    except Exception as ex:
        _LOGGER.debug("Nie udało się odtworzyć StudentInformation ze słownika: %s", ex)
        return None


class LibrusDataUpdateCoordinator(DataUpdateCoordinator):
    """Klasa zarzadzajaca pobieraniem danych z Librus."""

    def __init__(self, hass: HomeAssistant, client: Any) -> None:
        """Inicjalizacja koordynatora."""
        self.client = client
        self._seen_message_hrefs: set = set()
        self._seen_grade_ids: set = set()
        self._seen_homework_ids: set = set()
        self._seen_schedule_ids: set = set()
        self._seen_absence_ids: set = set()
        self._seen_note_ids: set = set()
        self._first_run: bool = True
        # Trwa awaria logowania (ostrzezenie w logu tylko raz na awarie)
        self._brak_logowania: bool = False
        self.store = Store(hass, 1, f"{DOMAIN}_cache_{self.client.username}")
        # Maly plik ze znacznikiem czasu ostatniego pobrania - zapisywany co cykl,
        # zeby duzy cache mozna bylo zapisywac tylko przy zmianie danych.
        self.meta_store = Store(hass, 1, f"{DOMAIN}_cache_meta_{self.client.username}")
        self._cache_pobrano: Optional[float] = None
        # Wersja integracji (z manifestu, ustawiana przy starcie) i wersja, ktora zapisala cache
        self.wersja_integracji: Optional[str] = None
        self._cache_wersja: Optional[str] = None
        self._ostatni_zapis: Optional[str] = None
        self.study_store: Optional[Store] = None
        self.study_completed_uids: set = set()
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._interwal_odpytywania(datetime.now()),
        )

    def _interwal_odpytywania(self, now: datetime) -> timedelta:
        """Interwał odpytywania z opcji: osobno dni robocze 7-16 i pozostały czas."""
        options = getattr(self.client, "options", None) or {}
        if 7 <= now.hour < 16 and now.weekday() < 5:
            minuty = options.get(CONF_SCAN_INTERVAL_SCHOOL, DEFAULT_SCAN_INTERVAL_SCHOOL)
        else:
            minuty = options.get(CONF_SCAN_INTERVAL_OTHER, DEFAULT_SCAN_INTERVAL_OTHER)
        return timedelta(minutes=int(minuty))

    async def async_init_study_store(self, entry_id: str) -> None:
        """Inicjalizacja współdzielonego Store dla zadań nauki."""
        if self.study_store is None:
            self.study_store = Store(self.hass, 1, f"librus_apix_{entry_id}_study")
            data = await self.study_store.async_load()
            if data and isinstance(data, dict):
                self.study_completed_uids = set(data.get("completed", []))

    async def async_load_cached_data(self) -> Optional[Dict[str, Any]]:
        """Wczytaj zapamiętany stan koordynatora z trwałego magazynu na dysku."""
        try:
            cached = await self.store.async_load()
            if isinstance(cached, dict) and "plan_lekcji" in cached and "oceny" in cached:
                self._ostatni_zapis = _zrzut_cache(cached)
                try:
                    meta = await self.meta_store.async_load()
                    if isinstance(meta, dict) and isinstance(meta.get("pobrano"), (int, float)):
                        self._cache_pobrano = float(meta["pobrano"])
                        wersja = meta.get("wersja")
                        self._cache_wersja = wersja if isinstance(wersja, str) else None
                except Exception as meta_ex:
                    _LOGGER.debug("Nie udało się wczytać znacznika czasu cache dla %s: %s", self.client.username, meta_ex)
                if "student_info" in cached and isinstance(cached["student_info"], dict):
                    cached["student_info"] = _student_info_from_dict(cached["student_info"])
                # Oceny wg bieżącej opcji pokazywania ocen niewliczanych (bez pytania
                # Librusa). Cache sprzed tej zmiany nie ma oceny_wszystkie - zostaje
                # jak był i poprawi się przy najbliższym pobraniu.
                if isinstance(cached.get("oceny_wszystkie"), list):
                    cached["oceny"], cached["oceny_wg_przedmiotu"] = self._przygotuj_oceny(cached["oceny_wszystkie"])
                _LOGGER.debug("Pomyślnie załadowano pełny stan z dyskowego cache dla %s", self.client.username)
                return cached
        except Exception as ex:
            _LOGGER.debug("Nie udało się wczytać pełnego stanu z cache dla %s: %s", self.client.username, ex)
        return None

    def wiek_cache(self) -> Optional[float]:
        """Ile sekund temu dane z cache zostaly pobrane z Librusa.

        None gdy nie wiadomo albo cache zapisala inna wersja integracji - po
        aktualizacji (np. z poprawka blednych danych) odswiezamy od razu.
        """
        if self._cache_pobrano is None or self._cache_wersja != self.wersja_integracji:
            return None
        return time.time() - self._cache_pobrano

    def _przygotuj_oceny(self, wszystkie: List[Dict]) -> tuple:
        """Widoczne oceny i oceny wg przedmiotu wg opcji integracji.

        Oceny niewliczane do sredniej (np. poprawione) sa domyslnie ukryte, jak
        w aplikacji Librusa; po wlaczeniu opcji widoczne z dopiskiem "*".
        """
        pokazuj = bool(self.client.options.get(CONF_POKAZUJ_NIELICZONE, False))
        widoczne = [g for g in wszystkie if pokazuj or g.get("liczona", True) is not False]
        oceny_wg_przedmiotu: Dict[str, List[Dict]] = {}
        for grade in widoczne:
            liczona = grade.get("liczona", True) is not False
            ocena = {
                "ocena": grade["grade"] if liczona else f"{grade['grade']}*",
                "data": grade["date"],
                "kategoria": grade["category"],
                "nauczyciel": grade["teacher"],
                "semestr": grade.get("semester"),
                "komentarz": grade.get("komentarz", ""),
                "opis": grade.get("opis", ""),
                "jest_nowa": _jest_nowa(grade["date"]),
                "liczona": liczona,
                "waga": grade.get("waga"),
                "poprawa_oceny": grade.get("poprawa_oceny", ""),
            }
            if grade.get("type") == "points":
                ocena["punktowa"] = True
                ocena["max_punktow"] = grade.get("max_points")
                ocena["procent"] = grade.get("percent")
            oceny_wg_przedmiotu.setdefault(grade["subject"], []).append(ocena)
        return widoczne, oceny_wg_przedmiotu

    def seed_seen_from_cached_data(self, data: Dict[str, Any]) -> None:
        """Zainicjalizuj zbiory widzianych elementów z cache, aby uniknąć fałszywych powiadomień."""
        self._first_run = False
        for msg in data.get("wiadomosci", []):
            if isinstance(msg, dict) and "href" in msg:
                self._seen_message_hrefs.add(msg["href"])
        # Wszystkie oceny, takze ukryte - wlaczenie opcji nie zglosi ich jako nowych
        for grade in data.get("oceny_wszystkie", data.get("oceny", [])):
            if isinstance(grade, dict) and "subject" in grade:
                self._seen_grade_ids.add(
                    (grade["subject"], grade.get("date"), grade.get("grade"))
                )
        for zadanie in data.get("zadania", []):
            if isinstance(zadanie, dict) and "przedmiot" in zadanie:
                self._seen_homework_ids.add(
                    (zadanie["przedmiot"], zadanie.get("termin"), zadanie.get("kategoria"))
                )
        for zdarzenie in data.get("terminarz", []):
            if isinstance(zdarzenie, dict) and "tytul" in zdarzenie:
                self._seen_schedule_ids.add(
                    (zdarzenie.get("data"), zdarzenie.get("tytul"), zdarzenie.get("przedmiot"))
                )
        for lekcja in data.get("tematy_lekcji", []):
            if isinstance(lekcja, dict):
                self._seen_absence_ids.add(_id_nieobecnosci(lekcja))
        for uwaga in data.get("uwagi", []):
            if isinstance(uwaga, dict) and "id" in uwaga:
                self._seen_note_ids.add(uwaga["id"])

    async def _async_update_data(self) -> Dict[str, Any]:
        """Pobierz aktualne dane z API Librus."""
        from datetime import date as _date
        current_sem = 1 if _date.today().month >= 9 else 2

        from contextlib import nullcontext
        lock = getattr(self.client, "_session_lock", None) or nullcontext()

        try:
            async with lock:
                # Bez sesji najpierw jedno logowanie. Gdy sie nie uda, konczymy
                # cykl - inaczej kazda metoda probowalaby logowac sie osobno.
                if not getattr(self.client, "_client", None) or not getattr(self.client, "_token", None):
                    if not await self.client.async_authenticate():
                        if not self.data:
                            raise UpdateFailed(
                                "Nie udało się zalogować do Librusa - pomijam ten cykl odświeżania"
                            )
                        # Sa dane: zostawiamy je bez zmian. UpdateFailed oznaczylby
                        # wszystkie encje jako niedostepne (bez atrybutow) na czas awarii.
                        if not self._brak_logowania:
                            _LOGGER.warning(
                                "Nie udało się zalogować do Librusa (%s) - pozostawiam ostatnie dane do czasu ponownego połączenia",
                                self.client.username,
                            )
                        else:
                            _LOGGER.debug("Nadal brak logowania do Librusa (%s) - pomijam cykl", self.client.username)
                        self._brak_logowania = True
                        return self.data
                if self._brak_logowania:
                    _LOGGER.info("Ponownie zalogowano do Librusa (%s)", self.client.username)
                    self._brak_logowania = False
                student_info = await self.client.async_get_student_information()
                grades = await self.client.async_get_grades()
                messages_count = self.client.options.get("fetch_messages_count", 10)
                messages = await self.client.async_get_messages(count=messages_count)
                homework_raw = await self.client.async_get_homework()
                schedule_raw = await self.client.async_get_schedule()
                plan_lekcji_raw = await self.client.async_get_timetable()
                
                # Restore from cache if failed
                if plan_lekcji_raw is None:
                    if self.data and "plan_lekcji" in self.data:
                        plan_lekcji_raw = self.data["plan_lekcji"]
                        _LOGGER.warning("Nie udało się pobrać planu lekcji. Używam danych z pamięci.")
                    else:
                        cached_data = await self.store.async_load()
                        if cached_data and "plan_lekcji" in cached_data:
                            plan_lekcji_raw = cached_data["plan_lekcji"]
                            _LOGGER.warning("Nie udało się pobrać planu lekcji. Używam danych z cache dyskowego.")

                frekwencja_raw = await self.client.async_get_attendance()
                ogloszenia_raw = await self.client.async_get_announcements()
                tematy_raw = await self.client.async_get_completed_lessons()
                frekwencja_stat_raw = await self.client.async_get_attendance_stats()
                uwagi_raw = await self.client.async_get_notes()
                if hasattr(self.client, "async_get_behavior") and callable(self.client.async_get_behavior):
                    beh_call = self.client.async_get_behavior()
                    if asyncio.iscoroutine(beh_call):
                        zachowanie_raw = await beh_call
                    elif isinstance(beh_call, dict) or beh_call is None:
                        zachowanie_raw = beh_call
                    else:
                        zachowanie_raw = None
                else:
                    zachowanie_raw = None

            prev = self.data or {}

            if grades is None:
                # Brak ocen moze oznaczac tymczasowy blad, ale rowniez konto bez
                # dostepu do dziennika ocen (np. konto przedszkolaka) - w obu
                # przypadkach nie blokujemy konfiguracji integracji, tylko
                # uzywamy danych z cache (jesli sa) lub pustej listy.
                _LOGGER.warning(
                    "Nie udalo sie pobrac ocen w tym cyklu - uzywam danych z cache "
                    "(jesli sa) lub pustej listy. Jesli blad sie powtarza, konto moze "
                    "nie miec dostepu do dziennika ocen (np. konto przedszkolaka)."
                )
                grades = prev.get("oceny_wszystkie", prev.get("oceny", []))

            if student_info is None:
                student_info = prev.get("student_info")

            zachowanie = (
                zachowanie_raw
                if zachowanie_raw is not None
                else prev.get("zachowanie", {})
            )

            # Wszystkie oceny (takze niewliczane) trafiaja do danych i cache, a
            # ukrywanie i "*" wg opcji stosujemy przy budowaniu stanu - takze
            # przy starcie z cache, wiec zmiana opcji dziala bez pytania Librusa.
            oceny_wszystkie = grades
            grades, oceny_wg_przedmiotu = self._przygotuj_oceny(oceny_wszystkie)

            wiadomosci = (
                self._build_wiadomosci(messages)
                if messages is not None
                else prev.get("wiadomosci", [])
            )
            zadania = (
                self._build_zadania(homework_raw)
                if homework_raw is not None
                else prev.get("zadania", [])
            )
            terminarz = schedule_raw if schedule_raw is not None else prev.get("terminarz", [])
            plan_lekcji = plan_lekcji_raw if plan_lekcji_raw is not None else prev.get("plan_lekcji", [])
            frekwencja = frekwencja_raw if frekwencja_raw is not None else prev.get("frekwencja", [])
            ogloszenia = ogloszenia_raw if ogloszenia_raw is not None else prev.get("ogloszenia", [])
            tematy_lekcji = tematy_raw if tematy_raw is not None else prev.get("tematy_lekcji", [])
            uwagi = uwagi_raw if uwagi_raw is not None else prev.get("uwagi", [])
            frekwencja_stat = (
                _frekwencja_statystyki(frekwencja_stat_raw, current_sem)
                if frekwencja_stat_raw is not None
                else prev.get("frekwencja_stat")
            )

            # Fuzja: Zdarzenia z terminarza -> plan lekcji (dodanie pola zdarzenie).
            # Zawsze na kopii bez sladow poprzedniej fuzji - plan z pamieci lub
            # cache jest juz scalony, a poprzedni stan uzywaja encje.
            plan_lekcji = _plan_bez_fuzji(plan_lekcji)
            if plan_lekcji:
                dni_wolne = {}
                if terminarz:
                    dni_wolne = {
                        t_ev.get("data"): t_ev.get("tytul")
                        for t_ev in terminarz
                        if t_ev.get("rodzaj") == "dzien_wolny" and t_ev.get("data")
                    }

                for day in plan_lekcji:
                    d_date = day.get("data")
                    if d_date in dni_wolne:
                        day["lekcje"] = []
                        day["dzien_wolny"] = dni_wolne[d_date]
                    else:
                        day.setdefault("dzien_wolny", None)

                if terminarz:
                    for t_ev in terminarz:
                        ev_date = t_ev.get("data")
                        ev_title = t_ev.get("tytul")
                        ev_subject = t_ev.get("przedmiot")
                        ev_num = t_ev.get("numer_lekcji")
                        ev_rodzaj = (t_ev.get("rodzaj") or "").lower()
                        is_exam = is_exam_event(t_ev)
                        is_substitution = (
                            ev_rodzaj == "zastepstwo"
                            or "zastępstwo" in (ev_title or "").lower()
                            or "zastepstwo" in (ev_title or "").lower()
                            or " na lekcji nr" in (ev_title or "").lower()
                        )
                        if is_substitution and not ev_subject:
                            # Zastepstwo nie ma osobnego przedmiotu: nazwa jest w tytule "(Biologia)"
                            ev_subject = ev_title
                        ev_teacher = None
                        if isinstance(t_ev.get("szczegoly"), dict):
                            raw_teacher = t_ev["szczegoly"].get("Nauczyciel")
                            if raw_teacher and str(raw_teacher).strip().lower() != "unknown":
                                ev_teacher = str(raw_teacher).strip()
                        
                        if not ev_date or not ev_title:
                            continue

                        if ev_date in dni_wolne:
                            continue
                            
                        for day in plan_lekcji:
                            if day.get("data") != ev_date:
                                continue
                                
                            day_lessons = day.get("lekcje", [])
                            # Sprawdz, czy w danym dniu uczen ma przedmiot odpowiadajacy zdarzeniu
                            day_has_matching_subject = False
                            if ev_subject:
                                ev_s_lower = ev_subject.strip().lower()
                                day_has_matching_subject = any(
                                    lek.get("przedmiot") and (
                                        ev_s_lower in lek["przedmiot"].strip().lower()
                                        or lek["przedmiot"].strip().lower() in ev_s_lower
                                    )
                                    for lek in day_lessons
                                )

                            scored_lekcje = []
                            max_score = 0
                            
                            for lekcja in day_lessons:
                                score = 0
                                lek_przedmiot = lekcja.get("przedmiot")
                                subject_match = False
                                if ev_subject and lek_przedmiot:
                                    ev_s_lower = ev_subject.strip().lower()
                                    lek_s_lower = lek_przedmiot.strip().lower()
                                    if ev_s_lower in lek_s_lower or lek_s_lower in ev_s_lower:
                                        subject_match = True

                                number_match = False
                                if ev_num and lekcja.get("numer"):
                                    try:
                                        # Terminarz moze zwrocic "4", "4-5"
                                        if str(lekcja["numer"]) in str(ev_num).split("-"):
                                            number_match = True
                                    except Exception as ex:
                                        _LOGGER.debug("Błąd podczas dopasowywania numeru lekcji ze zdarzenia: %s", ex)

                                teacher_match = False
                                lek_teacher = lekcja.get("nauczyciel")
                                if ev_teacher and lek_teacher:
                                    ev_t_lower = ev_teacher.lower()
                                    lek_t_lower = str(lek_teacher).strip().lower()
                                    if ev_t_lower in lek_t_lower or lek_t_lower in ev_t_lower:
                                        teacher_match = True

                                if is_substitution:
                                    # Zastępstwa: priorytet ma numer lekcji (zastąpienie przedmiotu na danym slocie)
                                    if number_match:
                                        score += 10
                                    if subject_match:
                                        score += 2
                                    if teacher_match:
                                        score += 1
                                else:
                                    # Sprawdziany, kartkówki i inne wpisy przedmiotowe
                                    if subject_match:
                                        score += 10
                                        if number_match:
                                            score += 5
                                        if teacher_match:
                                            score += 3
                                    elif not ev_subject:
                                        # Wpis ogólny bez określonego przedmiotu
                                        if number_match:
                                            score += 5
                                    elif not day_has_matching_subject and not is_exam:
                                        # Jeśli w danym dniu przedmiotu w ogóle nie ma i to nie jest sprawdzian
                                        if number_match:
                                            score += 2
                                    # Gdy to sprawdzian lub w planie jest właściwy przedmiot,
                                    # NIE dopasowujemy sprawdzianu do innej lekcji (score pozostaje 0)
                                
                                if score > 0:
                                    scored_lekcje.append((score, lekcja))
                                    if score > max_score:
                                        max_score = score
                                    
                            # Przypisz zdarzenie tylko do lekcji z najwyzszym wynikiem
                            if max_score > 0:
                                best_lekcje = [lek for score, lek in scored_lekcje if score == max_score]
                                for lekcja in best_lekcje:
                                    lekcja["zdarzenie"] = ev_title
                                    ev_opis = t_ev.get("szczegoly", {}).get("Opis")
                                    if ev_opis and str(ev_opis).lower() != "unknown":
                                        opis_str = str(ev_opis).strip()
                                        if len(opis_str) > 100:
                                            opis_str = opis_str[:97] + "..."
                                        lekcja["zdarzenie_opis"] = opis_str

                                # Jeśli dla sprawdzianu/kartkówki dopasowano lekcję z innym numerem, korygujemy numer w terminarzu
                                # (bez zmiany, gdy lekcja miesci sie w zakresie, np. "3-4")
                                first_best = best_lekcje[0]
                                orig_num = t_ev.get("numer_lekcji")
                                zakres = (
                                    [x.strip() for x in str(orig_num).split("-")]
                                    if orig_num not in (None, "", "unknown") else []
                                )
                                if is_exam and first_best.get("numer") is not None:
                                    if str(first_best["numer"]) not in zakres:
                                        _LOGGER.debug(
                                            "Skorygowano numer lekcji w terminarzu dla '%s' (%s): %s -> %s",
                                            ev_title,
                                            ev_subject,
                                            orig_num,
                                            first_best["numer"],
                                        )
                                        # Typ jak w oryginale (librus-apix zwraca tekst)
                                        t_ev["numer_lekcji"] = (
                                            str(first_best["numer"]) if isinstance(orig_num, str) else first_best["numer"]
                                        )
                                        godz_od = first_best.get("godzina_od")
                                        if godz_od and "??" not in godz_od and t_ev.get("godzina") in ("unknown", "", None):
                                            t_ev["godzina"] = godz_od
                            else:
                                # Jesli nie dopasowano lekcji z planu, a terminarz ma numer lekcji (np. poprawa po lekcjach).
                                # Nieobecnosc nauczyciela i dzien wolny nie sa zajeciami ucznia - nie dodajemy
                                # dla nich sztucznej lekcji (np. nieobecnosc nauczyciela na 8. lekcji, ktorej
                                # uczen nie ma, dawala lekcje "??:??" i psula plan dnia).
                                if ev_num and t_ev.get("rodzaj") not in ("nieobecnosc_nauczyciela", "dzien_wolny"):
                                    try:
                                        first_num = int(str(ev_num).split("-")[0])
                                        # Na zajetej lekcji uczen ma inny przedmiot (np. sprawdzian
                                        # innej grupy) - wpis zostaje w terminarzu, bez drugiej
                                        # lekcji o tym samym numerze w planie.
                                        if any(str(lk.get("numer")) == str(first_num) for lk in day.get("lekcje", [])):
                                            _LOGGER.debug(
                                                "Pomijam '%s' (%s) w planie: lekcja nr %s jest zajęta przez inny przedmiot",
                                                ev_title, ev_subject, first_num,
                                            )
                                            continue
                                        ev_opis = t_ev.get("szczegoly", {}).get("Opis")
                                        opis_str = str(ev_opis).strip() if ev_opis and str(ev_opis).lower() != "unknown" else ""
                                        if len(opis_str) > 100:
                                            opis_str = opis_str[:97] + "..."
                                            
                                        day.setdefault("lekcje", []).append({
                                            "przedmiot": ev_subject or ev_title,
                                            "nauczyciel_i_sala": "",
                                            "nauczyciel": "",
                                            "sala": "",
                                            "godzina_od": "??:??",
                                            "godzina_do": "??:??",
                                            "data": ev_date,
                                            "numer": first_num,
                                            "dzd": False,
                                            "odwolana": False,
                                            "zastepstwo": False,
                                            "zdarzenie": ev_title,
                                            "zdarzenie_opis": opis_str,
                                        })
                                        day["lekcje"].sort(key=lambda x: (int(x.get("numer") or 99), x.get("godzina_od") or "99:99"))
                                    except Exception as ex:
                                        _LOGGER.debug("Błąd podczas dodawania zdarzenia do planu lekcji: %s", ex)

            result = {
                "student_info": student_info,
                "oceny": grades,
                "oceny_wszystkie": oceny_wszystkie,
                "oceny_wg_przedmiotu": oceny_wg_przedmiotu,
                "wiadomosci": wiadomosci,
                "zadania": zadania,
                "terminarz": terminarz,
                "plan_lekcji": plan_lekcji,
                "frekwencja": frekwencja,
                "ogloszenia": ogloszenia,
                "tematy_lekcji": tematy_lekcji,
                "uwagi": uwagi,
                "zachowanie": zachowanie,
                "frekwencja_stat": frekwencja_stat,
                "semestr_biezacy": current_sem,
            }

            try:
                cache_copy = dict(result)
                cache_copy["student_info"] = _student_info_to_dict(student_info)
                # Pelny stan (duzy plik) zapisujemy tylko gdy dane sie zmienily -
                # mniej zapisow na karte SD.
                zrzut = _zrzut_cache(cache_copy)
                if zrzut is None or zrzut != self._ostatni_zapis:
                    await self.store.async_save(cache_copy)
                    self._ostatni_zapis = zrzut
                self._cache_pobrano = time.time()
                self._cache_wersja = self.wersja_integracji
                await self.meta_store.async_save(
                    {"pobrano": self._cache_pobrano, "wersja": self.wersja_integracji}
                )
            except Exception as save_ex:
                _LOGGER.debug("Nie udało się zapisać pełnego stanu do cache: %s", save_ex)

            # Pierwsze pobranie - tylko zapamietaj stan, nie wysylaj powiadomien
            if self._first_run:
                self._first_run = False
                for msg in wiadomosci:
                    self._seen_message_hrefs.add(msg["href"])
                for grade in oceny_wszystkie:
                    self._seen_grade_ids.add(
                        (grade["subject"], grade["date"], grade["grade"])
                    )
                for zadanie in zadania:
                    self._seen_homework_ids.add(
                        (zadanie["przedmiot"], zadanie["termin"], zadanie["kategoria"])
                    )
                for zdarzenie in terminarz:
                    self._seen_schedule_ids.add(
                        (zdarzenie["data"], zdarzenie["tytul"], zdarzenie["przedmiot"])
                    )
                for lekcja in tematy_lekcji:
                    self._seen_absence_ids.add(_id_nieobecnosci(lekcja))
                for uwaga in uwagi:
                    self._seen_note_ids.add(uwaga["id"])
            else:
                uczen = getattr(student_info, "name", "Nieznany uczeń") if student_info else "Nieznany uczeń"
                self._fire_events(wiadomosci, grades, uczen)
                self._fire_homework_events(zadania, uczen)
                self._fire_schedule_events(terminarz, uczen)
                self._fire_absence_events(tematy_lekcji, uczen)
                self._fire_note_events(uwagi, uczen)

            # Adaptacyjne odświeżanie (interwały z opcji integracji)
            self.update_interval = self._interwal_odpytywania(datetime.now())

            return result

        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Blad komunikacji z API: {err}") from err

    def _fire_events(self, messages: List[Dict], grades: List[Dict], uczen: str) -> None:
        """Wyslij zdarzenia HA dla nowych wiadomosci i ocen."""
        for msg in messages:
            href = msg.get("href", "")
            if href and href not in self._seen_message_hrefs:
                self._seen_message_hrefs.add(href)
                _LOGGER.debug("Nowa wiadomosc: %s", msg.get("title"))
                self.hass.bus.async_fire(
                    EVENT_NOWA_WIADOMOSC,
                    {
                        "uczen": uczen,
                        "nadawca": msg.get("author", ""),
                        "temat": msg.get("title", ""),
                        "data": msg.get("date", ""),
                        "ma_zalacznik": msg.get("has_attachment", False),
                    },
                )

        for grade in grades:
            grade_id = (grade["subject"], grade["date"], grade["grade"])
            if grade_id not in self._seen_grade_ids:
                self._seen_grade_ids.add(grade_id)
                _LOGGER.debug("Nowa ocena: %s %s", grade["subject"], grade["grade"])
                self.hass.bus.async_fire(
                    EVENT_NOWA_OCENA,
                    {
                        "uczen": uczen,
                        "przedmiot": grade["subject"],
                        "ocena": grade["grade"],
                        "data": grade["date"],
                        "kategoria": grade["category"],
                        "nauczyciel": grade["teacher"],
                        "opis": grade.get("opis", ""),
                        "liczona": grade.get("liczona", True) is not False,
                    },
                )

    def _fire_absence_events(self, lekcje: List[Dict], uczen: str) -> None:
        """Wyslij zdarzenia HA dla nowych wpisow frekwencji innych niz obecnosc.

        Zrodlo: zrealizowane lekcje z ostatnich 7 dni (wpis przy kazdej lekcji).
        Zmiana wpisu (np. nb -> u po usprawiedliwieniu) to nowe zdarzenie.
        """
        for lekcja in lekcje:
            if (lekcja.get("obecnosc") or "") in _BEZ_ZDARZENIA:
                continue
            wpis = _id_nieobecnosci(lekcja)
            if wpis in self._seen_absence_ids:
                continue
            self._seen_absence_ids.add(wpis)
            _LOGGER.debug("Nowy wpis frekwencji %s: %s lekcja %s", lekcja["obecnosc"], lekcja["data"], lekcja["numer"])
            self.hass.bus.async_fire(
                EVENT_NOWA_NIEOBECNOSC,
                {
                    "uczen": uczen,
                    "data": lekcja.get("data"),
                    "dzien_tygodnia": lekcja.get("dzien_tygodnia"),
                    "numer": lekcja.get("numer"),
                    "przedmiot": lekcja.get("przedmiot"),
                    "nauczyciel": lekcja.get("zastepca") or lekcja.get("nauczyciel"),
                    "rodzaj": lekcja.get("obecnosc"),
                    "opis": lekcja.get("obecnosc_opis"),
                },
            )

    def _fire_note_events(self, uwagi: List[Dict], uczen: str) -> None:
        """Wyslij zdarzenia HA dla nowych uwag."""
        for uwaga in uwagi:
            if uwaga["id"] in self._seen_note_ids:
                continue
            self._seen_note_ids.add(uwaga["id"])
            _LOGGER.debug("Nowa uwaga (%s) z %s", uwaga["rodzaj"], uwaga["data"])
            self.hass.bus.async_fire(
                EVENT_NOWA_UWAGA,
                {
                    "uczen": uczen,
                    "data": uwaga["data"],
                    "rodzaj": uwaga["rodzaj"],
                    "kategoria": uwaga["kategoria"],
                    "nauczyciel": uwaga["nauczyciel"],
                    "tresc": uwaga["tresc"],
                },
            )

    def _fire_schedule_events(self, terminarz: List[Dict], uczen: str) -> None:
        """Wyslij zdarzenia HA dla nowych zdarzen w kalendarzu."""
        for zdarzenie in terminarz:
            ev_id = (zdarzenie["data"], zdarzenie["tytul"], zdarzenie["przedmiot"])
            if not ev_id[2] and (ev_id[0], ev_id[1], ev_id[1]) in self._seen_schedule_ids:
                # Dawniej przedmiot powtarzal tytul: ten sam wpis, nie "nowe zdarzenie".
                self._seen_schedule_ids.add(ev_id)
                continue
            if ev_id not in self._seen_schedule_ids:
                self._seen_schedule_ids.add(ev_id)
                _LOGGER.debug("Nowe zdarzenie: %s %s %s", zdarzenie["data"], zdarzenie["przedmiot"], zdarzenie["tytul"])
                self.hass.bus.async_fire(
                    EVENT_NOWE_ZDARZENIE,
                    {
                        "uczen": uczen,
                        "data": zdarzenie["data"],
                        "tytul": zdarzenie["tytul"],
                        "przedmiot": zdarzenie["przedmiot"],
                        "godzina": zdarzenie["godzina"],
                    },
                )

    def _build_wiadomosci(self, messages: Optional[List[Dict]]) -> List[Dict]:
        """Oznacz nowe wiadomosci i zwroc liste."""
        result = []
        for msg in messages or []:
            msg["jest_nowa"] = _jest_nowa(msg.get("date", ""))
            result.append(msg)
        return result

    def _build_zadania(self, homework_raw) -> List[Dict]:
        """Przetworz liste Homework na liste dict, posortowana po terminie."""
        if not homework_raw:
            return []
        zadania = [
            {
                "przedmiot": hw.subject,
                "kategoria": hw.category,
                "nauczyciel": hw.teacher,
                "lekcja": hw.lesson,
                "data_zadania": hw.task_date,
                "termin": hw.completion_date,
                "href": hw.href,
            }
            for hw in homework_raw
        ]
        return sorted(zadania, key=lambda z: z["termin"])

    def _fire_homework_events(self, zadania: List[Dict], uczen: str) -> None:
        """Wyslij zdarzenia HA dla nowych zadan/sprawdzianow."""
        for zadanie in zadania:
            hw_id = (zadanie["przedmiot"], zadanie["termin"], zadanie["kategoria"])
            if hw_id not in self._seen_homework_ids:
                self._seen_homework_ids.add(hw_id)
                _LOGGER.debug("Nowe zadanie: %s %s", zadanie["przedmiot"], zadanie["kategoria"])
                self.hass.bus.async_fire(
                    EVENT_NOWE_ZADANIE,
                    {
                        "uczen": uczen,
                        "przedmiot": zadanie["przedmiot"],
                        "kategoria": zadanie["kategoria"],
                        "termin": zadanie["termin"],
                        "nauczyciel": zadanie["nauczyciel"],
                    },
                )


# _unrecorded_attributes w czujnikach: duze listy nie trafiaja do historii
# (recorder) - mniejsza baza i brak ostrzezenia o atrybutach > 16 KB.
# Atrybuty w stanie encji (karty, szablony) pozostaja bez zmian.


def _device_info(coordinator: Optional[DataUpdateCoordinator], config_entry: ConfigEntry) -> Dict[str, Any]:
    """Zwroc informacje o urzadzeniu."""
    data = coordinator.data if coordinator else None
    student_info = (data or {}).get("student_info")
    name = student_info.name if student_info else "Librus"
    return {
        "identifiers": {(DOMAIN, config_entry.entry_id)},
        "name": f"Librus - {name}",
        "manufacturer": "Librus",
        "model": "Synergia",
    }


class LibrusUczenSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z informacjami o uczniu."""

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Informacje o uczniu"
        self._attr_unique_id = f"{config_entry.entry_id}_uczen"
        self._attr_icon = "mdi:account-school"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> Optional[str]:
        info = (self.coordinator.data or {}).get("student_info")
        return info.name if info else None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        info = (self.coordinator.data or {}).get("student_info")
        if not info:
            return {}
        return {
            "klasa": info.class_name,
            "numer_w_klasie": info.number,
            "wychowawca": info.tutor,
            "szkola": info.school,
            "szczesliwy_numerek": info.lucky_number,
        }


class LibrusSzczesliwyNumerekSensor(CoordinatorEntity, SensorEntity):
    """Czujnik ze szczesliwym numerkiem dnia."""

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Szczesliwy numerek"
        self._attr_unique_id = f"{config_entry.entry_id}_szczesliwy_numerek"
        self._attr_icon = "mdi:numeric"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> Any:
        info = (self.coordinator.data or {}).get("student_info")
        return info.lucky_number if info else None


class LibrusOcenySensor(CoordinatorEntity, SensorEntity):
    """Czujnik z wszystkimi ocenami pogrupowanymi wedlug przedmiotow."""

    _unrecorded_attributes = frozenset({"oceny_wg_przedmiotu"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Oceny"
        self._attr_unique_id = f"{config_entry.entry_id}_oceny"
        self._attr_icon = "mdi:school"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("oceny", []))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        oceny_wg_przedmiotu = data.get("oceny_wg_przedmiotu", {})
        sa_nowe = any(
            g["jest_nowa"]
            for grades in oceny_wg_przedmiotu.values()
            for g in grades
        )
        return {
            "oceny_wg_przedmiotu": oceny_wg_przedmiotu,
            "liczba_ocen": len((self.coordinator.data or {}).get("oceny", [])),
            "liczba_przedmiotow": len(oceny_wg_przedmiotu),
            "sa_nowe_oceny": sa_nowe,
            "semestr": data.get("semestr_biezacy"),
        }


class LibrusPrzedmiotSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z ocenami dla konkretnego przedmiotu."""

    _unrecorded_attributes = frozenset({"oceny"})

    def __init__(
        self,
        coordinator: LibrusDataUpdateCoordinator,
        subject: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._subject = subject
        safe_name = subject.lower().replace(" ", "_").replace("/", "_")
        self._attr_has_entity_name = False
        self._attr_name = subject
        self._attr_unique_id = f"{config_entry.entry_id}_przedmiot_{safe_name}"
        self._attr_icon = "mdi:book-open-variant"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> Optional[str]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        if not oceny:
            return None
        return ", ".join(g["ocena"] for g in oceny)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        if not oceny:
            return {}

        srednia = _srednia_ocen(oceny)

        # Najnowsza ocena wg daty
        najnowsza: Optional[Dict] = None
        najnowsza_data: Optional[date] = None
        for g in oceny:
            for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
                try:
                    d = datetime.strptime(g["data"].strip(), fmt).date()
                    if najnowsza_data is None or d > najnowsza_data:
                        najnowsza_data = d
                        najnowsza = g
                    break
                except ValueError:
                    continue

        return {
            "oceny": oceny,
            "lista_ocen": ", ".join(g["ocena"] for g in oceny),
            "srednia": srednia,
            "srednia_procent": _srednia_procent(oceny),
            "najnowsza_ocena": najnowsza,
            "sa_nowe_oceny": any(g["jest_nowa"] for g in oceny),
        }


class LibrusSredniaOcenSensor(CoordinatorEntity, SensorEntity):
    """Czujnik ze srednia wszystkich ocen biezacego semestru (do wykresu)."""

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Srednia ocen"
        self._attr_unique_id = f"{config_entry.entry_id}_srednia_ocen"
        self._attr_icon = "mdi:chart-line"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = None

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> Optional[float]:
        data = self.coordinator.data or {}
        wszystkie = [
            g
            for oceny in data.get("oceny_wg_przedmiotu", {}).values()
            for g in oceny
        ]
        return _srednia_ocen(wszystkie)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        srednie_przedmiotow = {
            subject: _srednia_ocen(oceny)
            for subject, oceny in data.get("oceny_wg_przedmiotu", {}).items()
            if _srednia_ocen(oceny) is not None
        }
        return {
            "srednie_wg_przedmiotow": srednie_przedmiotow,
            "semestr": data.get("semestr_biezacy"),
        }


class LibrusSredniaPrzedmiotuSensor(CoordinatorEntity, SensorEntity):
    """Czujnik ze srednia ocen dla konkretnego przedmiotu (do wykresu)."""

    def __init__(
        self,
        coordinator: LibrusDataUpdateCoordinator,
        subject: str,
        config_entry: ConfigEntry,
    ) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._subject = subject
        safe_name = subject.lower().replace(" ", "_").replace("/", "_")
        self._attr_has_entity_name = False
        self._attr_name = f"Srednia {subject}"
        self._attr_unique_id = f"{config_entry.entry_id}_srednia_{safe_name}"
        self._attr_icon = "mdi:chart-bar"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = None

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> Optional[float]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        return _srednia_ocen(oceny)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        oceny = (self.coordinator.data or {}).get("oceny_wg_przedmiotu", {}).get(self._subject, [])
        return {
            "przedmiot": self._subject,
            "lista_ocen": ", ".join(g["ocena"] for g in oceny),
            "liczba_ocen": len(oceny),
            "srednia_procent": _srednia_procent(oceny),
        }


class LibrusTerminarzSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z nadchodzacymi zdarzeniami z kalendarza Librusa (biezacy + nastepny miesiac)."""

    _unrecorded_attributes = frozenset({"zdarzenia"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Terminarz"
        self._attr_unique_id = f"{config_entry.entry_id}_terminarz"
        self._attr_icon = "mdi:calendar-month"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("terminarz", []))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        terminarz = (self.coordinator.data or {}).get("terminarz", [])
        typy: Dict[str, int] = {}
        for z in terminarz:
            t = z.get("tytul", "")
            typy[t] = typy.get(t, 0) + 1
        return {
            "zdarzenia": terminarz,
            "liczba_zdarzen": len(terminarz),
            "typy": typy,
        }


class LibrusZadaniaSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z nadchodzacymi zadaniami i sprawdzianami (30 dni do przodu)."""

    _unrecorded_attributes = frozenset({"zadania"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Zadania"
        self._attr_unique_id = f"{config_entry.entry_id}_zadania"
        self._attr_icon = "mdi:calendar-check"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> int:
        return len((self.coordinator.data or {}).get("zadania", []))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        zadania = (self.coordinator.data or {}).get("zadania", [])
        kategorie: Dict[str, int] = {}
        for z in zadania:
            k = z.get("kategoria", "")
            kategorie[k] = kategorie.get(k, 0) + 1
        return {
            "zadania": zadania,
            "liczba_zadan": len(zadania),
            "kategorie": kategorie,
        }


class LibrusWiadomosciSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z wiadomosciami (temat i nadawca, bez pobierania tresci)."""

    _unrecorded_attributes = frozenset({"wiadomosci"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Wiadomosci"
        self._attr_unique_id = f"{config_entry.entry_id}_wiadomosci"
        self._attr_icon = "mdi:message-text"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> int:
        """Liczba nieprzeczytanych wiadomosci."""
        msgs = (self.coordinator.data or {}).get("wiadomosci", [])
        return sum(1 for m in msgs if m.get("unread", False))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        # Tyle wiadomości, ile pobrano (opcja fetch_messages_count)
        msgs = (self.coordinator.data or {}).get("wiadomosci", [])
        
        # Przygotuj liste wiadomosci
        wiadomosci_list = [
            {
                "nadawca": m["author"],
                "temat": m["title"],
                "data": m["date"],
                "nieprzeczytana": m.get("unread", False),
                "jest_nowa": m.get("jest_nowa", False),
                "ma_zalacznik": m.get("has_attachment", False),
                "tresc": m.get("content") or "",
            }
            for m in msgs
        ]
        
        # Wypelnij puste miejsca do 5 elementów, aby szablony kart (Jinja) nie rzucaly błędami indeksu
        while len(wiadomosci_list) < 5:
            wiadomosci_list.append({
                "nadawca": "",
                "temat": "Brak",
                "data": "",
                "nieprzeczytana": False,
                "jest_nowa": False,
                "ma_zalacznik": False,
                "tresc": "",
            })

        return {
            "wiadomosci": wiadomosci_list,
            "liczba_nieprzeczytanych": sum(1 for m in msgs if m.get("unread", False)),
            "sa_nowe_wiadomosci": any(m.get("jest_nowa", False) for m in msgs),
        }


class LibrusPlanLekcjiSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z planem lekcji na dzis i jutro."""

    _unrecorded_attributes = frozenset({
        "kolejne_7_dni",
        "dzisiaj",
        "jutro",
        "poniedzialek",
        "wtorek",
        "sroda",
        "czwartek",
        "piatek",
        "sobota",
        "niedziela",
    })

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Plan lekcji"
        self._attr_unique_id = f"{config_entry.entry_id}_plan_lekcji"
        self._attr_icon = "mdi:timetable"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> str:
        """Stan sensora to ilosc lekcji dzisiaj."""
        data = self.coordinator.data or {}
        plan = data.get("plan_lekcji", [])
        
        if not plan:
            return "0"
            
        dzisiaj_lekcje = plan[0].get("lekcje", [])
        return str(len(dzisiaj_lekcje))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        plan = data.get("plan_lekcji", [])
        
        wynik = {
            "kolejne_7_dni": plan
        }
        
        # Backward compatibility for old templates
        dni_tygodnia_map = {
            "Poniedziałek": "poniedzialek",
            "Wtorek": "wtorek",
            "Środa": "sroda",
            "Czwartek": "czwartek",
            "Piątek": "piatek",
            "Sobota": "sobota",
            "Niedziela": "niedziela"
        }
        
        for d in dni_tygodnia_map.values():
            wynik[d] = []
            
        for dzien in plan:
            nazwa = dzien.get("dzien_tygodnia")
            if nazwa in dni_tygodnia_map:
                klucz = dni_tygodnia_map[nazwa]
                wynik[klucz] = dzien.get("lekcje", [])
                
        if plan:
            wynik["dzisiaj"] = plan[0].get("lekcje", [])
            wynik["jutro"] = plan[1].get("lekcje", []) if len(plan) > 1 else []
        else:
            wynik["dzisiaj"] = []
            wynik["jutro"] = []
            
        return wynik


class LibrusFrekwencjaSensor(CoordinatorEntity, SensorEntity):
    """Czujnik frekwencji (nieobecnosci, spoznienia)."""

    _unrecorded_attributes = frozenset({"lista_wpisow"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Frekwencja"
        self._attr_unique_id = f"{config_entry.entry_id}_frekwencja"
        self._attr_icon = "mdi:account-check"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        frekwencja = data.get("frekwencja", [])
        nieobecnosci = sum(1 for f in frekwencja if f.get("symbol") in ["nb", "u"])
        return str(nieobecnosci)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        frekwencja = data.get("frekwencja", [])
        
        spoznienia = [f for f in frekwencja if f.get("symbol") == "sp"]
        nieobecnosci = [f for f in frekwencja if f.get("symbol") in ["nb", "u"]]
        stat = data.get("frekwencja_stat") or {}

        return {
            "lista_wpisow": frekwencja,
            "liczba_spoznien": len(spoznienia),
            "liczba_nieobecnosci": len(nieobecnosci),
            "liczba_nieusprawiedliwionych": sum(1 for f in frekwencja if f.get("symbol") == "nb"),
            "liczba_usprawiedliwionych": sum(1 for f in frekwencja if f.get("symbol") == "u"),
            "liczba_zwolnien": sum(1 for f in frekwencja if f.get("symbol") == "zw"),
            "frekwencja_procent": stat.get("procent_semestr"),
            "frekwencja_procent_rok": stat.get("procent_rok"),
            "lekcji_w_semestrze": stat.get("lekcji_w_semestrze"),
            "wpisy_wg_rodzaju": stat.get("rodzaje", {}),
        }


class LibrusTematyLekcjiSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z tematami zrealizowanych lekcji (ostatnie 7 dni) i obecnoscia na kazdej lekcji."""

    _unrecorded_attributes = frozenset({
        "lekcje",
        "dzisiaj",
        "lekcje_ostatniego_dnia",
        "nieobecnosci",
    })

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Tematy lekcji"
        self._attr_unique_id = f"{config_entry.entry_id}_tematy_lekcji"
        self._attr_icon = "mdi:book-open-page-variant"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> int:
        """Liczba zrealizowanych lekcji dzisiaj."""
        dzis = date.today().strftime("%Y-%m-%d")
        lekcje = (self.coordinator.data or {}).get("tematy_lekcji", [])
        return sum(1 for l in lekcje if l.get("data") == dzis)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        lekcje = (self.coordinator.data or {}).get("tematy_lekcji", [])
        dzis = date.today().strftime("%Y-%m-%d")
        ostatni_dzien = lekcje[0]["data"] if lekcje else None
        return {
            "lekcje": lekcje,
            "dzisiaj": [l for l in lekcje if l.get("data") == dzis],
            "ostatni_dzien": ostatni_dzien,
            "lekcje_ostatniego_dnia": [l for l in lekcje if l.get("data") == ostatni_dzien],
            "nieobecnosci": [l for l in lekcje if l.get("obecnosc") in ("nb", "u")],
        }


class LibrusUwagiSensor(CoordinatorEntity, SensorEntity):
    """Czujnik z uwagami (pozytywne, negatywne, neutralne)."""

    _unrecorded_attributes = frozenset({"uwagi"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Uwagi"
        self._attr_unique_id = f"{config_entry.entry_id}_uwagi"
        self._attr_icon = "mdi:account-alert"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> int:
        """Liczba uwag."""
        return len((self.coordinator.data or {}).get("uwagi", []))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        uwagi = (self.coordinator.data or {}).get("uwagi", [])
        return {
            "uwagi": uwagi,
            "liczba_pozytywnych": sum(1 for u in uwagi if u["rodzaj"] == "pozytywna"),
            "liczba_negatywnych": sum(1 for u in uwagi if u["rodzaj"] == "negatywna"),
            "liczba_neutralnych": sum(1 for u in uwagi if u["rodzaj"] == "neutralna"),
            "ostatnia": uwagi[0] if uwagi else None,
            "sa_nowe_uwagi": any(_jest_nowa(u["data"]) for u in uwagi),
        }


class LibrusZachowanieSensor(CoordinatorEntity, SensorEntity):
    """Czujnik ocen i punktów z zachowania."""

    _unrecorded_attributes = frozenset({"wpisy"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        """Inicjalizacja."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Zachowanie"
        self._attr_unique_id = f"{config_entry.entry_id}_zachowanie"
        self._attr_icon = "mdi:account-badge"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> Any:
        """Punkty lub ocena z zachowania."""
        zachowanie = (self.coordinator.data or {}).get("zachowanie") or {}
        current_sem = (self.coordinator.data or {}).get("semestr_biezacy", 1)
        # 1. Suma punktów w bieżącym okresie
        suma = zachowanie.get(f"suma_okres_{current_sem}")
        if suma is not None:
            return suma
        if zachowanie.get("suma_okres_1") is not None:
            return zachowanie.get("suma_okres_1")
        # 2. Przewidywana lub wystawiona ocena słowna
        ocena = (
            zachowanie.get(f"ocena_przewidywana_okres_{current_sem}")
            or zachowanie.get("ocena_przewidywana_okres_1")
            or zachowanie.get("ocena_srodroczna")
            or zachowanie.get("ocena_roczna")
        )
        if ocena:
            return ocena
        # 3. Punkty startowe
        if zachowanie.get("punkty_startowe") is not None:
            return zachowanie.get("punkty_startowe")
        return "Brak"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        zachowanie = (self.coordinator.data or {}).get("zachowanie") or {}
        wpisy = zachowanie.get("wpisy", [])
        return {
            "punkty_startowe": zachowanie.get("punkty_startowe"),
            "suma_okres_1": zachowanie.get("suma_okres_1"),
            "suma_okres_2": zachowanie.get("suma_okres_2"),
            "ocena_przewidywana_okres_1": zachowanie.get("ocena_przewidywana_okres_1", ""),
            "ocena_przewidywana_okres_2": zachowanie.get("ocena_przewidywana_okres_2", ""),
            "ocena_srodroczna": zachowanie.get("ocena_srodroczna", ""),
            "ocena_roczna": zachowanie.get("ocena_roczna", ""),
            "liczba_wpisow_pozytywnych": sum(1 for w in wpisy if w.get("typ") == "pozytywny"),
            "liczba_wpisow_negatywnych": sum(1 for w in wpisy if w.get("typ") == "negatywny"),
            "ostatni_wpis": wpisy[0] if wpisy else None,
            "wpisy": wpisy,
        }


class LibrusOgloszeniaSensor(CoordinatorEntity, SensorEntity):
    """Czujnik ogloszen szkolnych."""

    _unrecorded_attributes = frozenset({"lista_ogloszen"})

    def __init__(self, coordinator: LibrusDataUpdateCoordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Ogloszenia"
        self._attr_unique_id = f"{config_entry.entry_id}_ogloszenia"
        self._attr_icon = "mdi:bulletin-board"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def native_value(self) -> str:
        data = self.coordinator.data or {}
        ogloszenia = data.get("ogloszenia", [])
        return str(len(ogloszenia))

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        data = self.coordinator.data or {}
        ogloszenia = data.get("ogloszenia", [])
        
        return {
            "lista_ogloszen": ogloszenia,
        }



from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

class LibrusAISummarySensor(RestoreEntity, SensorEntity):
    """Czujnik z wygenerowanym podsumowaniem AI."""

    _unrecorded_attributes = frozenset({"pełny_tekst"})

    def __init__(self, *args, **kwargs) -> None:
        """Inicjalizacja."""
        if len(args) == 3:
            self.coordinator, self._config_entry, self._target = args
        elif len(args) == 2:
            self.coordinator = None
            self._config_entry, self._target = args
        else:
            self.coordinator = kwargs.get("coordinator")
            self._config_entry = kwargs.get("config_entry")
            self._target = kwargs.get("target")

        self._attr_has_entity_name = False
        self._attr_name = f"Podsumowanie AI ({'Rodzic' if self._target == 'rodzic' else 'Uczeń'})"
        self._attr_unique_id = f"{self._config_entry.entry_id}_ai_summary_{self._target}"
        self._attr_icon = "mdi:robot"
        self._attr_native_value = "Oczekuje na wygenerowanie..."
        self._attr_extra_state_attributes = {"pełny_tekst": "Oczekuje na wygenerowanie..."}
        self._unsub_dispatcher = None

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informacje o urzadzeniu."""
        coord = self.coordinator
        if coord is None and getattr(self, "hass", None) and DOMAIN in self.hass.data:
            client = self.hass.data[DOMAIN].get(self._config_entry.entry_id)
            if client and hasattr(client, "coordinator"):
                coord = client.coordinator
        return _device_info(coord, self._config_entry)

    async def async_added_to_hass(self) -> None:
        """Kiedy encja jest dodana do HA."""
        await super().async_added_to_hass()
        
        # Odtworzenie ostatniego stanu po restarcie
        last_state = await self.async_get_last_state()
        if last_state:
            self._attr_native_value = last_state.state
            if "pełny_tekst" in last_state.attributes:
                self._attr_extra_state_attributes["pełny_tekst"] = last_state.attributes["pełny_tekst"]
        
        # Nasłuchiwanie na sygnał od przycisku generowania
        signal = f"librus_ai_summary_{self._config_entry.entry_id}"
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, signal, self._handle_summary_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Kiedy encja jest usuwana."""
        if self._unsub_dispatcher:
            self._unsub_dispatcher()

    @callback
    def _handle_summary_update(self, summaries: dict) -> None:
        """Aktualizacja stanu na podstawie wygenerowanych danych z AI."""
        text = summaries.get(self._target, "Brak danych")
        
        # Ograniczenie native_value do 255 znaków
        short_text = text if len(text) <= 250 else text[:247] + "..."
        
        self._attr_native_value = short_text
        self._attr_extra_state_attributes["pełny_tekst"] = text
        from datetime import datetime
        self._attr_extra_state_attributes["ostatnia_aktualizacja"] = datetime.now().isoformat()
        self.async_write_ha_state()


class LibrusAIMessagesSummarySensor(RestoreEntity, SensorEntity):
    """Czujnik przechowujący podsumowanie wiadomości z AI."""

    _unrecorded_attributes = frozenset({"pełny_tekst"})

    def __init__(self, *args, **kwargs) -> None:
        """Inicjalizacja."""
        if len(args) == 3:
            self.coordinator, self._config_entry, self._target = args
        elif len(args) == 2:
            self.coordinator = None
            self._config_entry, self._target = args
        else:
            self.coordinator = kwargs.get("coordinator")
            self._config_entry = kwargs.get("config_entry")
            self._target = kwargs.get("target")

        self._attr_has_entity_name = False
        self._attr_name = f"Podsumowanie Wiadomości AI ({'Rodzic' if self._target == 'rodzic' else 'Uczeń'})"
        self._attr_unique_id = f"{self._config_entry.entry_id}_ai_messages_summary_{self._target}"
        self._attr_icon = "mdi:message-text"
        self._attr_native_value = "Oczekuje na wygenerowanie..."
        self._attr_extra_state_attributes = {"pełny_tekst": "Oczekuje na wygenerowanie..."}
        self._unsub_dispatcher = None

    @property
    def device_info(self) -> Dict[str, Any]:
        """Informacje o urzadzeniu."""
        coord = self.coordinator
        if coord is None and getattr(self, "hass", None) and DOMAIN in self.hass.data:
            client = self.hass.data[DOMAIN].get(self._config_entry.entry_id)
            if client and hasattr(client, "coordinator"):
                coord = client.coordinator
        return _device_info(coord, self._config_entry)

    async def async_added_to_hass(self) -> None:
        """Kiedy encja jest dodana do HA."""
        await super().async_added_to_hass()
        
        last_state = await self.async_get_last_state()
        if last_state:
            self._attr_native_value = last_state.state
            if "pełny_tekst" in last_state.attributes:
                self._attr_extra_state_attributes["pełny_tekst"] = last_state.attributes["pełny_tekst"]
        
        signal = f"librus_ai_messages_summary_{self._config_entry.entry_id}"
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, signal, self._handle_summary_update
        )

    async def async_will_remove_from_hass(self) -> None:
        """Kiedy encja jest usuwana."""
        if self._unsub_dispatcher:
            self._unsub_dispatcher()

    @callback
    def _handle_summary_update(self, summaries: dict) -> None:
        """Aktualizacja stanu na podstawie wygenerowanych danych z AI."""
        text = summaries.get(self._target, "Brak danych")
        short_text = text if len(text) <= 250 else text[:247] + "..."
        
        self._attr_native_value = short_text
        self._attr_extra_state_attributes["pełny_tekst"] = text
        from datetime import datetime
        self._attr_extra_state_attributes["ostatnia_aktualizacja"] = datetime.now().isoformat()
        self.async_write_ha_state()

