"""Plan lekcji: zastępstwo z nauczycielem o nazwisku dwuczłonowym (Issue #62).

Przy zastępstwie nauczyciel i sala były rozdzielane przy ostatnim myślniku,
więc nazwisko "Węgrzyn-Woźniak" trafiało częściowo do sali.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.librus_apix.__init__ import (
    LibrusApiClient,
    _rozdziel_nauczyciela_i_sale,
)


@pytest.mark.parametrize(
    "tekst, nauczyciel, sala",
    [
        ("Kowalski Jan - 5", "Kowalski Jan", "5"),
        ("Kowalski Jan s. 12", "Kowalski Jan", "s. 12"),
        ("Kowalski Jan sala 7", "Kowalski Jan", "sala 7"),
        ("Kowalski Jan", "Kowalski Jan", ""),
        ("Węgrzyn-Woźniak Milena", "Węgrzyn-Woźniak Milena", ""),
        ("Węgrzyn-Woźniak Milena - 12", "Węgrzyn-Woźniak Milena", "12"),
        ("Węgrzyn-Woźniak Milena s. 12", "Węgrzyn-Woźniak Milena", "s. 12"),
        ("", "", ""),
    ],
)
def test_rozdziel_nauczyciela_i_sale(tekst, nauczyciel, sala):
    assert _rozdziel_nauczyciela_i_sale(tekst) == (nauczyciel, sala)


def _klient():
    lib = MagicMock()
    lib.BASE_URL = "https://synergia.librus.pl"
    lib.cookies = {}
    lib.refresh_oauth.return_value = "fresh-oauth-token"
    lib.get.return_value.json.return_value = {"data": []}
    client = LibrusApiClient("user", "pass")
    client._client = lib
    client._token = "token"
    return client


def _tydzien(nauczyciel_i_sala, sala_swap="1 -> [brak]"):
    lekcja = SimpleNamespace(
        subject="Język polski",
        teacher_and_classroom=nauczyciel_i_sala,
        date_from="08:55",
        date_to="09:40",
        date=None,
        number=2,
        info={"zastępstwo": {
            "teacher_swap": "Mytych Barbara -> Węgrzyn-Woźniak Milena",
            "subject_swap": "Język angielski -> Język polski",
            "classroom_swap": sala_swap,
            "date_added": "2026-11-18",
        }},
    )
    return [[lekcja] for _ in range(7)]


async def _lekcja_dzis(tydzien):
    client = _klient()
    with patch("custom_components.librus_apix.plan_lekcji.get_timetable", return_value=tydzien):
        wynik = await client.async_get_timetable()
    dzis = next(d for d in wynik if d["data"] == date.today().strftime("%Y-%m-%d"))
    (lekcja,) = dzis["lekcje"]
    return lekcja


@pytest.mark.asyncio
async def test_62_zastepstwo_nazwisko_dwuczlonowe_bez_sali():
    lekcja = await _lekcja_dzis(_tydzien("Węgrzyn-Woźniak(nauczyciel) Milena"))
    assert lekcja["przedmiot"] == "Język angielski ➔ Język polski"
    assert lekcja["nauczyciel"] == "(Mytych Barbara ➔ Węgrzyn-Woźniak(nauczyciel) Milena)"
    assert lekcja["sala"] == "(1 ➔ brak)"
    assert lekcja["zastepstwo"] is True


@pytest.mark.asyncio
async def test_62_zastepstwo_nazwisko_dwuczlonowe_z_sala():
    lekcja = await _lekcja_dzis(_tydzien("Węgrzyn-Woźniak Milena - 12", "1 -> 12"))
    assert lekcja["nauczyciel"] == "(Mytych Barbara ➔ Węgrzyn-Woźniak Milena)"
    assert lekcja["sala"] == "(1 ➔ 12)"


@pytest.mark.asyncio
async def test_zastepstwo_sala_z_przedrostkiem_bez_zmiany():
    """Ta sama sala zapisana jako "s. 1" nie jest pokazywana jako zmiana."""
    lekcja = await _lekcja_dzis(_tydzien("Węgrzyn-Woźniak Milena s. 1", "1"))
    assert lekcja["nauczyciel"] == "(Mytych Barbara ➔ Węgrzyn-Woźniak Milena)"
    assert lekcja["sala"] == "s. 1"


@pytest.mark.asyncio
async def test_zastepstwo_nazwisko_jednoczlonowe_bez_zmian():
    tydzien = _tydzien("Nowak Anna - 5", "1 -> 5")
    tydzien[0][0].info["zastępstwo"]["teacher_swap"] = "Mytych Barbara -> Nowak Anna"
    for dzien in tydzien:
        dzien[0] = tydzien[0][0]
    lekcja = await _lekcja_dzis(tydzien)
    assert lekcja["nauczyciel"] == "(Mytych Barbara ➔ Nowak Anna)"
    assert lekcja["sala"] == "(1 ➔ 5)"
