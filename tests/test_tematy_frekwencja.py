"""Testy tematów zrealizowanych lekcji i statystyk frekwencji.

Strona "Zrealizowane lekcje" i gateway API
frekwencji są tu zamockowane.
"""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.librus_apix.__init__ import LibrusApiClient, _parse_completed_lessons
from custom_components.librus_apix.sensor import _frekwencja_statystyki


def _row(date, nr, subject_teacher, topic, attendance=None, etablica=True):
    """Wiersz jak na prawdziwej stronie Librusa (z kolumną e-Tablica lub bez)."""
    box = ""
    if attendance:
        box = (
            '<p class="box"><a href="javascript:void(0)" '
            f'title="Rodzaj: {attendance[1]}&lt;br&gt; Data: {date}">{attendance[0]}</a></p>'
        )
    etab = "<td></td>" if etablica else ""
    return (
        f'<tr><td class="center small">{date}</td><td class="tiny">pon.</td>'
        f"<td>{nr}</td><td>{subject_teacher}</td><td>{topic}</td><td></td>{etab}"
        f"<td>{box}</td></tr>"
    )


def _page(*rows):
    return '<table class="decorated"><tbody>' + "".join(rows) + "</tbody></table>"


def test_parse_with_etablica_column_and_substitution():
    html = _page(
        _row("2026-10-05", "6", "Matematyka , Kowalska Anna [Nowak Maria Ewa]",
             "Ułamki zwykłe", ("ob", "obecność")),
        _row("2026-10-05", "1", "Język polski , Wiśniewska Ewa",
             "Rzeczownik", ("nb", "nieobecność")),
    )
    mat, pol = _parse_completed_lessons(html)
    assert mat["przedmiot"] == "Matematyka"
    assert mat["nauczyciel"] == "Kowalska Anna"
    assert mat["zastepca"] == "Nowak Maria Ewa"
    assert mat["zastepstwo"] is True
    assert mat["obecnosc"] == "ob"
    assert mat["obecnosc_opis"] == "obecność"
    assert pol["obecnosc"] == "nb"
    assert pol["zastepstwo"] is False
    assert pol["numer"] == 1


def test_parse_without_etablica_and_without_attendance():
    html = _page(_row("05.10.2026", "x", "Fizyka , Zielińska Joanna", "Ruch", None, etablica=False))
    (fiz,) = _parse_completed_lessons(html)
    assert fiz["data"] == "2026-10-05"
    assert fiz["numer"] is None  # nieczytelny numer -> None, nie string
    assert fiz["temat"] == "Ruch"
    assert fiz["obecnosc"] == ""


@pytest.mark.asyncio
async def test_completed_lessons_all_pages_deduplicated_and_sorted():
    strona_0 = _page(
        _row("2026-10-05", "2", "Język polski , Wiśniewska Ewa", "Rzeczownik", ("ob", "obecność")),
        _row("2026-10-05", "1", "Matematyka , Kowalska Anna", "Ułamki dziesiętne", ("nb", "nieobecność")),
    )
    strona_1 = _page(_row("2026-10-06", "3", "Chemia , Lewandowska Ola", "Mieszaniny", ("ob", "obecność")))

    lib = MagicMock()

    def fake_post(url, data):
        return MagicMock(text=strona_0 if data["numer_strony1001"] == 0 else strona_1)

    lib.post.side_effect = fake_post
    client = LibrusApiClient("user", "pass")
    client._client = lib
    client._token = "token"

    # 2 strony + powtórzona ostatnia (Librus zwraca ją dla numeru poza zakresem)
    with patch("librus_apix.completed_lessons.get_max_page_number", return_value=2):
        result = await client.async_get_completed_lessons()

    assert len(result) == 3  # duplikaty usunięte
    assert [(l["data"], l["numer"]) for l in result] == [
        ("2026-10-06", 3), ("2026-10-05", 1), ("2026-10-05", 2),
    ]
    assert result[1]["obecnosc"] == "nb"


def _client(lib=None):
    client = LibrusApiClient("user", "pass")
    client._client = lib or MagicMock()
    client._token = "token"
    return client


@pytest.mark.asyncio
async def test_attendance_stats_from_gateway():
    lib = MagicMock()
    lib.cookies = {}
    lib.refresh_oauth.return_value = "oauth"
    lib.get.return_value.json.return_value = {
        "Attendances": [
            {"Type": {"Id": 100}, "Semester": 1},
            {"Type": {"Id": 100}, "Semester": 1},
            {"Type": {"Id": 2}, "Semester": 1},
            {"Type": {"Id": 1}, "Semester": 1},
            {"Type": {"Id": 99999}, "Semester": 1},  # nieznany rodzaj
        ]
    }
    result = await _client(lib).async_get_attendance_stats()
    assert result == [("ob", 1), ("ob", 1), ("sp", 1), ("nb", 1), ("inne", 1)]


@pytest.mark.asyncio
async def test_attendance_stats_failure_returns_none():
    lib = MagicMock()
    lib.cookies = {}
    lib.get.return_value.json.return_value = {"Status": "Error"}
    assert await _client(lib).async_get_attendance_stats() is None


def test_frekwencja_statystyki():
    wpisy = [("ob", 1), ("ob", 1), ("sp", 1), ("nb", 1), ("ob", 2)]
    stat = _frekwencja_statystyki(wpisy, 1)
    assert stat["procent_semestr"] == 75.0  # ob, ob, sp obecne; nb nie
    assert stat["procent_rok"] == 80.0
    assert stat["lekcji_w_semestrze"] == 4
    assert stat["rodzaje"] == {"ob": 2, "sp": 1, "nb": 1}


def test_frekwencja_statystyki_pusta():
    stat = _frekwencja_statystyki([], 1)
    assert stat["procent_semestr"] is None
    assert stat["lekcji_w_semestrze"] == 0
