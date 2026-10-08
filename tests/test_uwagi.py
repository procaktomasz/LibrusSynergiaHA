"""Testy uwag (gateway API Notes) - dane fikcyjne."""

from unittest.mock import MagicMock

import pytest

from custom_components.librus_apix.__init__ import LibrusApiClient, _map_notes
from custom_components.librus_apix.sensor import EVENT_NOWA_UWAGA, LibrusUwagiSensor

NOTES = [
    {"Id": 1, "Date": "2026-09-14", "Positive": 1, "Text": "Pomoc koledze w lekcji.",
     "Category": {"Id": 10}, "Teacher": {"Id": 100}, "Public": True},
    {"Id": 2, "Date": "2026-10-01", "Positive": 0, "Text": " Rozmowy na lekcji. ",
     "Category": {"Id": 11}, "Teacher": {"Id": 101}, "Public": True},
    {"Id": 3, "Date": "2026-10-05", "Positive": 2, "Text": "Brak stroju.",
     "Category": {"Id": 12}, "Teacher": {"Id": 999}, "Public": True},
]
KATEGORIE = {10: "pozytywna", 11: "negatywna", 12: "neutralna"}
OSOBY = {100: "Kowalska Anna", 101: "Nowak Jan"}


def test_mapowanie_uwag():
    uwagi = _map_notes(NOTES, KATEGORIE, OSOBY)
    assert [u["id"] for u in uwagi] == [3, 2, 1]  # od najnowszej
    neutralna, negatywna, pozytywna = uwagi
    assert pozytywna["rodzaj"] == "pozytywna"
    assert pozytywna["nauczyciel"] == "Kowalska Anna"
    assert negatywna["rodzaj"] == "negatywna"
    assert negatywna["tresc"] == "Rozmowy na lekcji."
    assert neutralna["rodzaj"] == "neutralna"
    assert neutralna["nauczyciel"] == ""  # nieznany nauczyciel


def _lib(payloads):
    lib = MagicMock()
    lib.BASE_URL = "https://synergia.librus.pl"
    lib.cookies = {}
    lib.refresh_oauth.return_value = "oauth"
    lib.get.side_effect = lambda url: MagicMock(json=MagicMock(return_value=payloads[url.rsplit("2.0/", 1)[1]]))
    return lib


def _client(lib):
    client = LibrusApiClient("user", "pass")
    client._client = lib
    client._token = "token"
    return client


@pytest.mark.asyncio
async def test_pobieranie_uwag():
    lib = _lib({
        "Notes": {"Notes": NOTES},
        "Notes/Categories": {"Categories": [{"Id": k, "CategoryName": v} for k, v in KATEGORIE.items()]},
        "Users": {"Users": [{"Id": 100, "FirstName": "Anna", "LastName": "Kowalska"}]},
    })
    uwagi = await _client(lib).async_get_notes()
    assert len(uwagi) == 3
    assert uwagi[2]["nauczyciel"] == "Kowalska Anna"
    assert uwagi[1]["kategoria"] == "negatywna"


@pytest.mark.asyncio
async def test_brak_uwag_i_blad():
    assert await _client(_lib({"Notes": {"Notes": []}})).async_get_notes() == []
    assert await _client(_lib({"Notes": {"Status": "Error"}})).async_get_notes() is None


def test_czujnik_uwag():
    coordinator = MagicMock()
    coordinator.data = {"uwagi": _map_notes(NOTES, KATEGORIE, OSOBY)}
    sensor = LibrusUwagiSensor(coordinator, MagicMock(entry_id="e1"))
    assert sensor.native_value == 3
    attrs = sensor.extra_state_attributes
    assert (attrs["liczba_pozytywnych"], attrs["liczba_negatywnych"], attrs["liczba_neutralnych"]) == (1, 1, 1)
    assert attrs["ostatnia"]["id"] == 3


async def test_zdarzenie_nowej_uwagi(hass):
    from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator

    coord = LibrusDataUpdateCoordinator(hass, MagicMock())
    stare = _map_notes(NOTES[:2], KATEGORIE, OSOBY)
    coord._seen_note_ids = {u["id"] for u in stare}
    zdarzenia = []
    hass.bus.async_listen(EVENT_NOWA_UWAGA, lambda e: zdarzenia.append(e.data))
    coord._fire_note_events(_map_notes(NOTES, KATEGORIE, OSOBY), "Jan Testowy")
    await hass.async_block_till_done()
    assert len(zdarzenia) == 1
    assert zdarzenia[0]["rodzaj"] == "neutralna"
    assert zdarzenia[0]["uczen"] == "Jan Testowy"
