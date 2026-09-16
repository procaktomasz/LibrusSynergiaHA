"""Testy scalania zajęć dodatkowych (DZD) z planem lekcji.

DZD pochodzą z osobnego gateway-endpointu
/gateway/api/2.0/Timetables/OtherActivitiesRegister, który jest tu zamockowany,
aby sprawdzić, że wpisy trafiają do właściwego dnia w `async_get_timetable`.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.librus_apix.__init__ import LibrusApiClient


def _period():
    """Jedna zwykła lekcja: 08:00 nr 1, bez zastępstw (info puste)."""
    return SimpleNamespace(
        subject="Matematyka",
        teacher_and_classroom="Kowalski Jan - 5",
        date_from="08:00",
        date_to="08:45",
        date=None,
        number=1,
        info=None,
    )


def _fake_week():
    """Tydzień = 7 dni, każdy z jedną lekcją 08:00. get_timetable jest wołane
    dwa razy (bieżący + następny tydzień), więc łącznie 14 dni."""
    return [[_period()] for _ in range(7)]


def _dzd_payload(day: str):
    """Odpowiedź gateway: jedno DZD wpasowane w siatkę (08:00), jedno poza nią
    (15:00) oraz jedno odwołane (do pominięcia)."""
    return {
        "data": [
            {
                "status": "ACTUAL",
                "date": day,
                "startTime": "08:00",
                "endTime": "08:45",
                "title": "Kółko szachowe",
                "teacherName": "Nowak Anna",
                "classroom": {"name": "9"},
            },
            {
                "status": "ACTUAL",
                "date": day,
                "startTime": "15:00",
                "endTime": "15:45",
                "title": "Klub debat",
                "teacherName": "Zielińska Ewa",
                "classroom": {"name": "12"},
            },
            {
                "status": "CANCELLED",
                "date": day,
                "startTime": "16:00",
                "endTime": "16:45",
                "title": "Odwołane zajęcia",
                "teacherName": "Mazur Piotr",
                "classroom": {"name": "1"},
            },
        ]
    }


def _client_with_gateway(payload):
    """LibrusApiClient z zamockowanym klientem biblioteki: refresh_oauth +
    client.get(...).json() zwraca `payload`."""
    lib = MagicMock()
    lib.BASE_URL = "https://synergia.librus.pl"
    lib.cookies = {}
    lib.refresh_oauth.return_value = "fresh-oauth-token"
    lib.get.return_value.json.return_value = payload

    client = LibrusApiClient("user", "pass")
    client._client = lib
    client._token = "token"
    return client


async def _today_after_merge(payload):
    """Uruchom async_get_timetable z zamockowanym planem i podaną odpowiedzią
    gateway; zwróć dzień „dziś" (pierwszy zwracany) po scaleniu DZD."""
    client = _client_with_gateway(payload)
    with patch("librus_apix.timetable.get_timetable", return_value=_fake_week()):
        result = await client.async_get_timetable()
    today = date.today().strftime("%Y-%m-%d")
    return next(d for d in result if d["data"] == today)


@pytest.mark.asyncio
async def test_dzd_merged_into_timetable():
    today = date.today().strftime("%Y-%m-%d")
    dzis = await _today_after_merge(_dzd_payload(today))
    by_title = {l["przedmiot"]: l for l in dzis["lekcje"]}

    # zwykła lekcja nietknięta
    assert "Matematyka" in by_title

    # DZD wpasowane w siatkę dzwonków dostaje numer lekcji (08:00 -> 1)
    kolko = by_title["Kółko szachowe"]
    assert kolko["dzd"] is True
    assert kolko["numer"] == 1
    assert "Nowak Anna" in kolko["nauczyciel_i_sala"]
    assert "9" in kolko["nauczyciel_i_sala"]

    # DZD poza siatką: numer = None (zgodność wsteczna — nigdy nie znak/string)
    klub = by_title["Klub debat"]
    assert klub["dzd"] is True
    assert klub["numer"] is None

    # odwołane DZD pominięte
    assert "Odwołane zajęcia" not in by_title

    # dzień posortowany po godzinie rozpoczęcia
    times = [l["godzina_od"] for l in dzis["lekcje"]]
    assert times == sorted(times)


@pytest.mark.asyncio
async def test_timetable_without_dzd_unchanged():
    """Pusta lista DZD nie zmienia planu i nie dodaje pola 'dzd'."""
    dzis = await _today_after_merge({"data": []})
    assert [l["przedmiot"] for l in dzis["lekcje"]] == ["Matematyka"]
    assert all("dzd" not in l for l in dzis["lekcje"])


@pytest.mark.asyncio
async def test_dzd_fetch_failure_degrades_to_plain_plan():
    """Błąd gateway (np. brak pola 'data') => plan bez DZD, bez wyjątku."""
    dzis = await _today_after_merge({"Status": "Error"})  # brak "data"
    assert [l["przedmiot"] for l in dzis["lekcje"]] == ["Matematyka"]
