"""Testy szybkiego startu HA (C1-C4): swiezy cache, importy, jednokrotne parsowanie, zapis na dysk."""

import sys
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.librus_apix import (
    LibrusApiClient,
    _parse_behavior_grades,
    _parse_point_grades,
)
from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator

from test_init import mock_config_entry, mock_librus_client  # noqa: F401
from test_oceny_punktowe import WIERSZ_WF, _strona

CACHE = {
    "plan_lekcji": [],
    "oceny": [{"subject": "Matematyka", "grade": "5", "date": "2026-10-01",
               "category": "Test", "teacher": "Jan Kowalski", "type": "numeric"}],
    "oceny_wg_przedmiotu": {"Matematyka": []},
    "wiadomosci": [],
    "student_info": None,
}


# --- C1: start ze swiezym cache bez natychmiastowego pobierania ---


async def _setup(hass, entry, client, wiek):
    with patch("custom_components.librus_apix.LibrusApiClient", return_value=client), \
         patch.object(LibrusDataUpdateCoordinator, "async_load_cached_data",
                      AsyncMock(return_value=dict(CACHE))), \
         patch.object(LibrusDataUpdateCoordinator, "wiek_cache", return_value=wiek):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_swiezy_cache_bez_odpytywania_przy_starcie(
    hass: HomeAssistant, mock_config_entry, mock_librus_client  # noqa: F811
):
    """Cache sprzed 5 minut: start bez zapytan do Librusa, odswiezenie gdy minie interwal."""
    await _setup(hass, mock_config_entry, mock_librus_client, wiek=300)
    mock_librus_client.async_get_grades.assert_not_awaited()

    coord = mock_librus_client.coordinator
    pozostalo = coord.update_interval.total_seconds() - 300
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=pozostalo + 1))
    await hass.async_block_till_done()
    mock_librus_client.async_get_grades.assert_awaited()


async def test_stary_cache_odswiezany_od_razu(
    hass: HomeAssistant, mock_config_entry, mock_librus_client  # noqa: F811
):
    """Cache starszy niz interwal: odswiezenie w tle od razu po starcie (jak dotad)."""
    await _setup(hass, mock_config_entry, mock_librus_client, wiek=10 * 3600)
    mock_librus_client.async_get_grades.assert_awaited()


async def test_cache_bez_znacznika_czasu_odswiezany_od_razu(
    hass: HomeAssistant, mock_config_entry, mock_librus_client  # noqa: F811
):
    """Cache z poprzedniej wersji (bez znacznika czasu) traktujemy jak nieaktualny."""
    await _setup(hass, mock_config_entry, mock_librus_client, wiek=None)
    mock_librus_client.async_get_grades.assert_awaited()


async def test_wiek_cache_z_pliku_meta(hass: HomeAssistant):
    """Znacznik czasu pobrania jest wczytywany razem z cache."""
    client = MagicMock()
    client.username = "test_user"
    client.options = {}
    coord = LibrusDataUpdateCoordinator(hass, client)
    coord.store = MagicMock()
    coord.store.async_load = AsyncMock(return_value=dict(CACHE))
    coord.meta_store = MagicMock()
    coord.meta_store.async_load = AsyncMock(return_value={"pobrano": 1000.0})
    with patch("custom_components.librus_apix.sensor.time.time", return_value=1600.0):
        assert await coord.async_load_cached_data() is not None
        assert coord.wiek_cache() == 600.0


async def test_wiek_cache_bez_pliku_meta(hass: HomeAssistant):
    client = MagicMock()
    client.username = "test_user"
    client.options = {}
    coord = LibrusDataUpdateCoordinator(hass, client)
    assert coord.wiek_cache() is None


# --- Cache z innej wersji integracji odswiezany od razu ---


def _koordynator_z_meta(hass, wersja_integracji, meta):
    client = MagicMock()
    client.username = "test_user"
    client.options = {}
    coord = LibrusDataUpdateCoordinator(hass, client)
    coord.wersja_integracji = wersja_integracji
    coord.store = MagicMock()
    coord.store.async_load = AsyncMock(return_value=dict(CACHE))
    coord.meta_store = MagicMock()
    coord.meta_store.async_load = AsyncMock(return_value=meta)
    return coord


@pytest.mark.parametrize(
    "meta",
    [
        {"pobrano": 1000.0, "wersja": "3.0.1"},  # poprzednie wydanie
        {"pobrano": 1000.0},  # plik meta z 3.0.1 (bez pola wersja)
    ],
    ids=["inna_wersja", "brak_wersji"],
)
async def test_cache_z_innej_wersji_traktowany_jak_nieaktualny(hass: HomeAssistant, meta):
    coord = _koordynator_z_meta(hass, "3.0.2", meta)
    with patch("custom_components.librus_apix.sensor.time.time", return_value=1060.0):
        assert await coord.async_load_cached_data() is not None
        assert coord.wiek_cache() is None


async def test_cache_z_tej_samej_wersji_ma_wiek(hass: HomeAssistant):
    coord = _koordynator_z_meta(hass, "3.0.2", {"pobrano": 1000.0, "wersja": "3.0.2"})
    with patch("custom_components.librus_apix.sensor.time.time", return_value=1060.0):
        await coord.async_load_cached_data()
        assert coord.wiek_cache() == 60.0


async def test_meta_zapisuje_wersje_integracji(hass: HomeAssistant):
    client = MagicMock(spec=LibrusApiClient)
    client.username = "test_user"
    client.options = {}
    client._client = MagicMock()
    client._token = "token"
    for name in (
        "async_get_student_information", "async_get_attendance_stats", "async_get_behavior",
    ):
        setattr(client, name, AsyncMock(return_value=None))
    for name in (
        "async_get_grades", "async_get_messages", "async_get_homework", "async_get_schedule",
        "async_get_timetable", "async_get_attendance", "async_get_announcements",
        "async_get_completed_lessons", "async_get_notes",
    ):
        setattr(client, name, AsyncMock(return_value=[]))
    coord = LibrusDataUpdateCoordinator(hass, client)
    coord.wersja_integracji = "3.0.2"
    coord.store = MagicMock()
    coord.store.async_save = AsyncMock()
    coord.meta_store = MagicMock()
    coord.meta_store.async_save = AsyncMock()

    await coord._async_update_data()

    zapis = coord.meta_store.async_save.await_args.args[0]
    assert zapis["wersja"] == "3.0.2"
    assert isinstance(zapis["pobrano"], float)


def _wersja_z_manifestu() -> str:
    import json
    import pathlib

    sciezka = pathlib.Path(__file__).parent.parent / "custom_components" / "librus_apix" / "manifest.json"
    return json.loads(sciezka.read_text(encoding="utf-8"))["version"]


def _wczytanie_cache(wersja_w_meta):
    """Podmiana async_load_cached_data: cache sprzed minuty z podana wersja w meta."""
    import time

    async def _load(self):
        self._cache_pobrano = time.time() - 60
        self._cache_wersja = wersja_w_meta
        return dict(CACHE)

    return _load


async def test_start_po_aktualizacji_odswieza_od_razu(
    hass: HomeAssistant, mock_config_entry, mock_librus_client  # noqa: F811
):
    """Swiezy cache, ale zapisany przez starsza wersje: odswiezenie od razu po starcie."""
    with patch("custom_components.librus_apix.LibrusApiClient", return_value=mock_librus_client), \
         patch.object(LibrusDataUpdateCoordinator, "async_load_cached_data", _wczytanie_cache("0.0.1")):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_librus_client.coordinator.wersja_integracji == _wersja_z_manifestu()
    mock_librus_client.async_get_grades.assert_awaited()


async def test_start_bez_aktualizacji_ze_swiezym_cache(
    hass: HomeAssistant, mock_config_entry, mock_librus_client  # noqa: F811
):
    """Swiezy cache z tej samej wersji: start bez zapytan do Librusa (jak dotad)."""
    with patch("custom_components.librus_apix.LibrusApiClient", return_value=mock_librus_client), \
         patch.object(LibrusDataUpdateCoordinator, "async_load_cached_data",
                      _wczytanie_cache(_wersja_z_manifestu())):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    mock_librus_client.async_get_grades.assert_not_awaited()


# --- C2: moduly biblioteki ladowane razem z integracja ---


def test_moduly_biblioteki_zaladowane_przy_imporcie():
    """Importy nie czekaja na pierwsze uzycie w petli zdarzen."""
    for mod in (
        "librus_apix.messages", "librus_apix.homework", "librus_apix.schedule",
        "librus_apix.timetable", "librus_apix.student_information",
        "librus_apix.attendance", "librus_apix.announcements",
        "librus_apix.completed_lessons", "librus_apix.grades",
        "bs4", "soupsieve", "custom_components.librus_apix.sensor",
        "custom_components.librus_apix.plan_lekcji",
    ):
        assert mod in sys.modules, mod


# --- C3: strona ocen parsowana raz ---


def test_parsery_przyjmuja_gotowy_soup():
    from bs4 import BeautifulSoup

    html = _strona(WIERSZ_WF)
    soup = BeautifulSoup(html, "lxml")
    assert _parse_point_grades(soup) == _parse_point_grades(html)
    assert _parse_behavior_grades(soup) == _parse_behavior_grades(html)


async def test_strona_ocen_parsowana_raz():
    """Jedno BeautifulSoup na pobranie ocen zamiast trzech."""
    import bs4

    client = LibrusApiClient("test_user", "test_pass")
    client._client = MagicMock()
    client._token = "token"
    client._client.post.return_value.text = _strona(WIERSZ_WF)

    oryginal = bs4.BeautifulSoup.__init__
    utworzone = []

    def _licz(self, *args, **kwargs):
        utworzone.append(1)
        return oryginal(self, *args, **kwargs)

    with patch.object(bs4.BeautifulSoup, "__init__", _licz), \
         patch("librus_apix.grades._extract_grades_numeric", return_value=([], {})), \
         patch("librus_apix.grades._extract_grades_descriptive", return_value=[]):
        oceny = await client.async_get_grades()
    assert len(utworzone) == 1
    assert oceny is not None


# --- C4: pelny stan zapisywany tylko przy zmianie ---


@pytest.fixture
def koordynator(hass):
    client = MagicMock(spec=LibrusApiClient)
    client.username = "test_user"
    client.options = {}
    client._client = MagicMock()
    client._token = "token"
    client.async_authenticate = AsyncMock(return_value=True)
    client.async_get_grades = AsyncMock(return_value=[])
    for name in (
        "async_get_student_information", "async_get_attendance_stats", "async_get_behavior",
    ):
        setattr(client, name, AsyncMock(return_value=None))
    for name in (
        "async_get_messages", "async_get_homework", "async_get_schedule", "async_get_timetable",
        "async_get_attendance", "async_get_announcements", "async_get_completed_lessons",
        "async_get_notes",
    ):
        setattr(client, name, AsyncMock(return_value=[]))
    coord = LibrusDataUpdateCoordinator(hass, client)
    coord.store = MagicMock()
    coord.store.async_save = AsyncMock()
    coord.store.async_load = AsyncMock(return_value=None)
    coord.meta_store = MagicMock()
    coord.meta_store.async_save = AsyncMock()
    coord.meta_store.async_load = AsyncMock(return_value=None)
    return coord


async def test_zapis_tylko_przy_zmianie_danych(koordynator):
    await koordynator._async_update_data()
    await koordynator._async_update_data()
    assert koordynator.store.async_save.await_count == 1
    # Znacznik czasu pobrania zapisywany co cykl (maly plik)
    assert koordynator.meta_store.async_save.await_count == 2

    koordynator.client.async_get_announcements.return_value = [
        {"tytul": "Wywiadowka", "nadawca": "", "opis": "", "data": "2026-10-14"}
    ]
    await koordynator._async_update_data()
    assert koordynator.store.async_save.await_count == 2


async def test_brak_zapisu_po_restarcie_gdy_dane_te_same(koordynator):
    """Po wczytaniu cache identyczne dane z Librusa nie powoduja zapisu."""
    wynik = await koordynator._async_update_data()
    zapisane = koordynator.store.async_save.await_args.args[0]

    koordynator.store.async_save.reset_mock()
    koordynator._ostatni_zapis = None
    koordynator.store.async_load = AsyncMock(return_value=dict(zapisane))
    assert await koordynator.async_load_cached_data() is not None
    assert wynik is not None

    await koordynator._async_update_data()
    koordynator.store.async_save.assert_not_awaited()
