"""Testy zadan od nauczycieli (HomeWorkAssignments, konto ucznia) - dane fikcyjne."""

import copy
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.librus_apix.__init__ import (
    LibrusApiClient,
    _map_teacher_assignments,
)
from custom_components.librus_apix.sensor import (
    EVENT_NOWE_ZADANIE_NAUCZYCIELA,
    LibrusZadaniaNauczycielaSensor,
)

API = "https://api.librus.pl/2.0/"
JUTRO = (date.today() + timedelta(days=1)).isoformat()
WCZORAJ = (date.today() - timedelta(days=1)).isoformat()


def _zadanie(id_, termin, **kw):
    z = {
        "Id": id_, "Topic": f"Temat {id_}", "Text": " Przeczytaj rozdział 3. ",
        "Date": "2026-11-02", "DueDate": f"{termin} 00:00:00",
        "Lesson": {"Id": 7, "Url": API + "Lesson/7"},
        "Category": {"Id": 5, "Url": API + "HomeWorkAssignments/Categories/5"},
        "Teacher": {"Id": 100, "Url": API + "Users/100"},
        "StudentsWhoRead": [], "StudentsWhoMarkedAsDone": [],
        "HomeworkAssigmentFiles": [], "MustSendAttachFile": False,
    }
    z.update(kw)
    return z


ZADANIA = [
    _zadanie(2, JUTRO, StudentsWhoRead=[{"Id": 1}], HomeworkAssigmentFiles=[{"Id": 9}]),
    _zadanie(1, WCZORAJ),
    _zadanie(3, JUTRO, StudentsWhoMarkedAsDone=[{"Id": 1}]),
]

ODPOWIEDZI = {
    "HomeWorkAssignments": {"HomeWorkAssignments": copy.deepcopy(ZADANIA)},
    # Prawdziwe API: adres lekcji z zadania (".../Lesson/7") zwraca 404, sa listy
    "Lessons": {"Lessons": [{"Id": 7, "Subject": {"Id": 3}, "Teacher": {"Id": 100}}]},
    "Subjects": {"Subjects": [{"Id": 3, "Name": "Geografia", "Short": "geo"}]},
    "HomeWorkAssignments/Categories": {"Categories": [{"Id": 5, "CategoryName": "Projekt"}]},
    "Users": {"Users": [{"Id": 100, "FirstName": "Anna", "LastName": "Kowalska"}]},
}


def _lib(odpowiedzi, kod=200):
    lib = MagicMock()
    lib.BASE_URL = "https://synergia.librus.pl"
    lib.cookies = {}
    lib.refresh_oauth.return_value = "oauth"

    def get(url):
        assert url.startswith("https://synergia.librus.pl/gateway/api/2.0/")
        klucz = url.rsplit("2.0/", 1)[1]
        return MagicMock(status_code=kod, json=MagicMock(return_value=odpowiedzi.get(klucz, {})))

    lib.get.side_effect = get
    return lib


def _client(lib):
    client = LibrusApiClient("1234567u", "haslo")
    client._client = lib
    client._token = "token"
    return client


@pytest.mark.asyncio
async def test_pobieranie_zadan_od_nauczycieli():
    lib = _lib(ODPOWIEDZI)
    client = _client(lib)
    zadania = await client.async_get_teacher_assignments()
    assert [z["id"] for z in zadania] == [1, 2, 3]  # wg terminu
    z = zadania[1]
    assert (z["przedmiot"], z["kategoria"], z["nauczyciel"]) == ("Geografia", "Projekt", "Kowalska Anna")
    assert z["tresc"] == "Przeczytaj rozdział 3."
    assert z["termin"] == JUTRO
    assert (z["przeczytane"], z["pliki"], z["zrobione"]) == (True, 1, False)
    assert zadania[2]["zrobione"] is True

    # Slowniki w pamieci: drugie pobranie pyta tylko o liste zadan
    lib.get.reset_mock()
    await client.async_get_teacher_assignments()
    assert lib.get.call_count == 1


@pytest.mark.asyncio
async def test_brak_kategorii_i_nowa_kategoria(monkeypatch):
    import custom_components.librus_apix.__init__ as librus

    odp = copy.deepcopy(ODPOWIEDZI)
    odp["HomeWorkAssignments"]["HomeWorkAssignments"][0]["Category"] = None
    odp["HomeWorkAssignments"]["HomeWorkAssignments"][1]["Category"] = {"Id": 6, "Url": "x"}
    client = _client(_lib(odp))
    zadania = await client.async_get_teacher_assignments()
    po_id = {z["id"]: z for z in zadania}
    assert po_id[2]["kategoria"] == ""  # zadanie bez kategorii
    assert po_id[1]["kategoria"] == ""  # kategorii 6 nie ma jeszcze w slowniku
    assert po_id[1]["przedmiot"] == "Geografia"

    # Nieznana kategoria: lista odswiezana dopiero po SLOWNIK_ODSWIEZANIE
    odp["HomeWorkAssignments/Categories"]["Categories"].append({"Id": 6, "CategoryName": "Referat"})
    zadania = await client.async_get_teacher_assignments()
    assert {z["id"]: z for z in zadania}[1]["kategoria"] == ""
    monkeypatch.setattr(librus, "SLOWNIK_ODSWIEZANIE", 0)
    zadania = await client.async_get_teacher_assignments()
    assert {z["id"]: z for z in zadania}[1]["kategoria"] == "Referat"


@pytest.mark.asyncio
async def test_zadania_brak_dostepu_i_blad():
    # Konto bez modulu (np. rodzica): pusta lista, bez ponownego logowania, przerwa na dobe
    client = _client(_lib({}, kod=403))
    assert await client.async_get_teacher_assignments() == []
    assert client._client is not None
    assert client._modul_niedostepny("zadania_nauczyciela")
    assert await _client(_lib({"HomeWorkAssignments": {"Status": "Error"}})).async_get_teacher_assignments() is None


def test_czujnik_zadan_od_nauczycieli():
    coordinator = MagicMock()
    coordinator.data = {"zadania_nauczyciela": _map_teacher_assignments([dict(z) for z in ZADANIA])}
    sensor = LibrusZadaniaNauczycielaSensor(coordinator, MagicMock(entry_id="e1"))
    # po terminie i zrobione sie nie licza
    assert sensor.native_value == 1
    attrs = sensor.extra_state_attributes
    assert attrs["liczba_zadan"] == 3
    assert attrs["liczba_wszystkich"] == 3
    assert attrs["najblizsze"]["id"] == 2
    assert attrs["najblizszy_termin"] == JUTRO


async def test_zdarzenia_bez_zalewu_po_aktualizacji(hass):
    from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator

    coord = LibrusDataUpdateCoordinator(hass, MagicMock())
    zdarzenia = []
    hass.bus.async_listen(EVENT_NOWE_ZADANIE_NAUCZYCIELA, lambda e: zdarzenia.append(e.data))

    stare_zad = _map_teacher_assignments([dict(z) for z in ZADANIA[:1]])
    # Pierwsze pobranie (np. po aktualizacji integracji): tylko zapamietanie stanu
    coord._fire_assignment_events(stare_zad, "Jan Testowy")
    await hass.async_block_till_done()
    assert zdarzenia == []

    coord._fire_assignment_events(_map_teacher_assignments([dict(z) for z in ZADANIA]), "Jan Testowy")
    await hass.async_block_till_done()
    po_temacie = {z["temat"]: z for z in zdarzenia}
    assert sorted(po_temacie) == ["Temat 1", "Temat 3"]
    assert po_temacie["Temat 1"]["przedmiot"] == ""


def test_stan_z_cache_ustawia_widziane():
    from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator

    coord = LibrusDataUpdateCoordinator.__new__(LibrusDataUpdateCoordinator)
    coord._seen_message_hrefs = set()
    coord._seen_grade_ids = set()
    coord._seen_homework_ids = set()
    coord._seen_schedule_ids = set()
    coord._seen_absence_ids = set()
    coord._seen_note_ids = set()
    coord._seen_assignment_ids = None
    # Cache sprzed aktualizacji: stan nadal nieznany (pierwsze pobranie bez zdarzen)
    coord.seed_seen_from_cached_data({})
    assert coord._seen_assignment_ids is None
    coord.seed_seen_from_cached_data({"zadania_nauczyciela": [{"id": 4}]})
    assert coord._seen_assignment_ids == {4}


@pytest.mark.asyncio
async def test_koordynator_pobiera_zadania_od_nauczycieli(hass):
    from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator

    klient = MagicMock()
    klient.options = {}
    klient.username = "uczen"
    klient._client = klient._token = object()
    for metoda in (
        "async_get_student_information", "async_get_grades", "async_get_messages",
        "async_get_homework", "async_get_schedule", "async_get_timetable",
        "async_get_attendance", "async_get_announcements", "async_get_completed_lessons",
        "async_get_attendance_stats", "async_get_notes", "async_get_behavior",
    ):
        setattr(klient, metoda, AsyncMock(return_value=None))
    klient.async_get_grades.return_value = []
    klient.async_get_teacher_assignments = AsyncMock(return_value=[{"id": 1, "termin": JUTRO}])

    coord = LibrusDataUpdateCoordinator(hass, klient)
    coord.store = MagicMock(async_save=AsyncMock(), async_load=AsyncMock(return_value=None))
    coord.meta_store = MagicMock(async_save=AsyncMock())
    dane = await coord._async_update_data()
    assert dane["zadania_nauczyciela"] == [{"id": 1, "termin": JUTRO}]

    # Blad pobierania: zostaja poprzednie dane
    coord.data = dane
    klient.async_get_teacher_assignments.return_value = None
    dane = await coord._async_update_data()
    assert dane["zadania_nauczyciela"] == [{"id": 1, "termin": JUTRO}]


def test_czujnik_pomija_stare_zadania():
    stare = (date.today() - timedelta(days=22)).isoformat()
    graniczne = (date.today() - timedelta(days=21)).isoformat()
    coordinator = MagicMock()
    coordinator.data = {"zadania_nauczyciela": _map_teacher_assignments(
        [_zadanie(1, stare), _zadanie(2, graniczne), _zadanie(3, JUTRO)]
    )}
    attrs = LibrusZadaniaNauczycielaSensor(coordinator, MagicMock(entry_id="e1")).extra_state_attributes
    assert [z["id"] for z in attrs["zadania"]] == [2, 3]
    assert (attrs["liczba_zadan"], attrs["liczba_wszystkich"]) == (2, 3)
