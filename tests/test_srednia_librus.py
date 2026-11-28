"""Średnie ocen (Issue #65): średnia z Librusa, a gdy jej brak - wyliczona.

- ocena "0" i oceny spoza skali 1-6 nie wchodzą do średniej,
- oceny ze znakiem przed cyfrą ("+5", "-5") są liczone,
- średnia jest ważona; waga 0 jest pomijana tylko wtedy, gdy w ocenach są
  wagi większe od 0 (biblioteka wpisuje 0 także przy braku pola "Waga").
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.librus_apix import _srednie_z_librusa
from custom_components.librus_apix.sensor import (
    LibrusPrzedmiotSensor,
    LibrusSredniaOcenSensor,
    LibrusSredniaPrzedmiotuSensor,
    _srednia_ocen,
)

from test_oceny_niewliczane import _g, _koordynator


def _o(ocena, waga=1):
    return {"ocena": ocena, "waga": waga}


# --- Wyliczanie średniej ---


def test_65_plus_przed_cyfra():
    assert _srednia_ocen([_o("+5")] * 7) == 5.5


def test_65_minus_przed_cyfra():
    assert _srednia_ocen([_o("-5"), _o("5")]) == 4.88


def test_65_przyrodnicza():
    assert _srednia_ocen([_o("5"), _o("5"), _o("+5"), _o("+5")]) == 5.25


def test_65_zero_z_waga_0_pominiete():
    assert _srednia_ocen([_o("5"), _o("5-"), _o("5"), _o("0", 0)]) == 4.92


def test_65_zero_bez_wagi_pominiete():
    oceny = [_o("6")] * 4 + [_o("0", None)] + [_o("6")] * 2
    assert _srednia_ocen(oceny) == 6.0


def test_srednia_wazona():
    assert _srednia_ocen([_o("5", 2), _o("3", 1)]) == 4.33


def test_szkola_bez_wag_srednia_arytmetyczna():
    """Bez pola "Waga" biblioteka daje 0 dla każdej oceny - liczymy jak dotąd."""
    assert _srednia_ocen([_o("5", 0), _o("4", 0)]) == 4.5
    assert _srednia_ocen([{"ocena": "5"}, {"ocena": "4"}]) == 4.5


def test_waga_0_obok_wag_pominieta():
    assert _srednia_ocen([_o("5", 1), _o("1", 0)]) == 5.0


def test_same_zera_bez_sredniej():
    assert _srednia_ocen([_o("0"), _o("0")]) is None


def test_znaki_po_cyfrze_jak_dotad():
    assert _srednia_ocen([_o("5+"), _o("4-")]) == 4.62
    assert _srednia_ocen([_o("4=")]) == 4.0


# --- Średnia z Librusa ---


def _gpa(sem, wartosc, przedmiot="Matematyka"):
    return SimpleNamespace(semester=sem, gpa=wartosc, subject=przedmiot)


def test_srednie_z_librusa_biezacy_semestr():
    srednie = {
        "Matematyka": [_gpa(1, "4.50"), _gpa(2, "-"), _gpa(0, "4.50")],
        "Religia": [_gpa(1, "4,92", "Religia"), _gpa(2, "5.00", "Religia"), _gpa(0, "4.96", "Religia")],
    }
    assert _srednie_z_librusa(srednie, 1) == {"Matematyka": 4.5, "Religia": 4.92}
    assert _srednie_z_librusa(srednie, 2) == {"Religia": 5.0}


@pytest.mark.parametrize("wartosc", ["-", "", 0.0, "0.00", "abc", None, "7.5"])
def test_srednie_z_librusa_bez_wartosci(wartosc):
    assert _srednie_z_librusa({"Matematyka": [_gpa(1, wartosc)]}, 1) == {}


def test_srednie_z_librusa_brak_danych():
    assert _srednie_z_librusa(None, 1) == {}
    assert _srednie_z_librusa({}, 1) == {}


# --- Czujniki ---


def _dane(srednie_librus=None):
    oceny = [{"ocena": "5", "waga": 1, "jest_nowa": False, "data": "2026-11-20"},
             {"ocena": "4", "waga": 1, "jest_nowa": False, "data": "2026-11-21"}]
    dane = {"oceny_wg_przedmiotu": {"Matematyka": oceny}, "semestr_biezacy": 1}
    if srednie_librus is not None:
        dane["srednie_librus"] = srednie_librus
    return dane


def _koord(dane):
    c = MagicMock()
    c.data = dane
    return c


def _wpis():
    return MagicMock(entry_id="e1", options={})


def test_czujnik_sredniej_przedmiotu_z_librusa():
    s = LibrusSredniaPrzedmiotuSensor(_koord(_dane({"Matematyka": 4.8})), "Matematyka", _wpis())
    assert s.native_value == 4.8
    assert s.extra_state_attributes["zrodlo_sredniej"] == "librus"


def test_czujnik_sredniej_przedmiotu_wyliczona():
    s = LibrusSredniaPrzedmiotuSensor(_koord(_dane()), "Matematyka", _wpis())
    assert s.native_value == 4.5
    assert s.extra_state_attributes["zrodlo_sredniej"] == "wyliczona"


def test_czujnik_przedmiotu_srednia_z_librusa():
    attrs = LibrusPrzedmiotSensor(_koord(_dane({"Matematyka": 4.8})), "Matematyka", _wpis()).extra_state_attributes
    assert attrs["srednia"] == 4.8
    assert attrs["zrodlo_sredniej"] == "librus"


def test_czujnik_sredniej_ocen_srednie_przedmiotow_z_librusa():
    s = LibrusSredniaOcenSensor(_koord(_dane({"Matematyka": 4.8})), _wpis())
    assert s.extra_state_attributes["srednie_wg_przedmiotow"] == {"Matematyka": 4.8}
    assert s.native_value == 4.5  # średnia wszystkich ocen - wyliczana


# --- Koordynator ---


async def test_koordynator_zapisuje_srednie_z_librusa(hass):
    koord = _koordynator(hass, [_g("5")])
    koord.client._srednie_librus = {"język angielski": 5.0}
    data = await koord._async_update_data()
    assert data["srednie_librus"] == {"język angielski": 5.0}


async def test_koordynator_zachowuje_srednie_gdy_oceny_nie_pobrane(hass):
    koord = _koordynator(hass, None)
    koord.client._srednie_librus = {}
    koord.data = {"srednie_librus": {"język angielski": 4.0}, "oceny_wszystkie": [_g("4")]}
    data = await koord._async_update_data()
    assert data["srednie_librus"] == {"język angielski": 4.0}


async def test_koordynator_klient_bez_srednich(hass):
    data = await _koordynator(hass, [_g("5")])._async_update_data()
    assert data["srednie_librus"] == {}
