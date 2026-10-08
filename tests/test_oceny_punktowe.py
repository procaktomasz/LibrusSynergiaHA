"""Testy odczytu ocen punktowych (sekcja "Oceny punktowe", issue #22).

HTML wiersza oparty na fragmencie wklejonym w #22 (dane zanonimizowane).
Nie mamy konta z ocenami punktowymi - test sprawdza parser na tym fragmencie.
"""

from custom_components.librus_apix.__init__ import _parse_point_grades
from custom_components.librus_apix.sensor import _srednia_ocen


def _a(kategoria, data, href_id, wartosc, extra=""):
    return (
        '<span class="grade-box" style="float: left; background-color:#FFD700; ">'
        f'<a title="Kategoria: {kategoria}&lt;br&gt;Data: {data}&lt;br&gt;Nauczyciel: Nazwisko Imie'
        f'&lt;br&gt;Licz do wyniku: TAK&lt;br&gt;Licz do puli: TAK&lt;br&gt;Dodał: Nazwisko Imie{extra}" '
        f'href="/przegladaj_oceny_punktowe/szczegoly/{href_id}">{wartosc}</a></span>'
    )


WIERSZ_WF = (
    '<tr class="line0"><td class="center micro screen-only">'
    '<img src="/images/tree_colapsed.png" id="przedmioty_OP_96760_node" onclick="showHideOP.ShowHide(96760);"></td>'
    '<td>Wychowanie fizyczne</td><td class="">'
    + _a("Aktywność  (0-100)", "2026-09-21 (pon.)", 17169, "100")
    + _a("Siatka Gra (0-100)", "2026-09-28 (pon.)", 31421, "80", "&lt;br/&gt;Obowiązek wyk. zadania: TAK")
    + _a("Praca na WF (0-100)", "2026-09-29 (wt.)", 35028, "100",
         "&lt;br/&gt;Data zapowiedzi: 2024-09-03&lt;br/&gt;Data realizacji: 2025-06-20")
    + '</td><td class="center"> - </td><td>Brak ocen</td><td class="center"> - </td><td class="center"> - </td></tr>'
    '<tr class="line1" name="przedmioty_OP_all" id="przedmioty_OP_96760" style="display: none;">'
    '<td>&nbsp;</td><td colspan="9"><img id="przedmioty_OP_x"></td></tr>'
)

WIERSZ_SKALA_20_II_OKRES = (
    '<tr class="line1"><td class="center micro screen-only">'
    '<img id="przedmioty_OP_11111_node"></td>'
    '<td>Matematyka</td><td>Brak ocen</td><td class="center"> - </td><td class="">'
    + _a("Kartkówka (0-20)", "2027-03-02 (wt.)", 50001, "14")
    + '</td><td class="center"> - </td><td class="center"> - </td></tr>'
)

ZWYKLA_OCENA = (
    '<tr class="line0"><td class="center micro screen-only"><img id="przedmioty_12_node"></td>'
    '<td>Fizyka</td><td><span class="grade-box"><a title="Kategoria: sprawdzian&lt;br&gt;Data: 2026-09-20 (pn.)" '
    'href="/przegladaj_oceny/szczegoly/1">5</a></span></td></tr>'
)


def _strona(*wiersze):
    return '<table class="decorated stretch"><tbody>' + "".join(wiersze) + "</tbody></table>"


def test_oceny_punktowe_z_issue_22():
    oceny = _parse_point_grades(_strona(WIERSZ_WF))
    assert [o["grade"] for o in oceny] == ["100", "80", "100"]
    akt, siatka, _ = oceny
    assert akt["subject"] == "Wychowanie fizyczne"
    assert akt["category"] == "Aktywność"
    assert akt["max_points"] == 100
    assert akt["percent"] == 100.0
    assert akt["date"] == "2026-09-21"
    assert akt["teacher"] == "Nazwisko Imie"
    assert akt["semester"] == 1
    assert akt["counts"] is True
    assert akt["type"] == "points"
    assert siatka["category"] == "Siatka Gra"
    assert siatka["percent"] == 80.0


def test_inna_skala_i_drugi_okres():
    (o,) = _parse_point_grades(_strona(WIERSZ_SKALA_20_II_OKRES))
    assert o["semester"] == 2
    assert o["max_points"] == 20
    assert o["percent"] == 70.0


def test_zwykle_oceny_sa_pomijane():
    assert _parse_point_grades(_strona(ZWYKLA_OCENA)) == []
    assert _parse_point_grades("<html></html>") == []


def test_srednia_z_procentow():
    oceny = [
        {"ocena": "100", "punktowa": True, "procent": 100.0},
        {"ocena": "14", "punktowa": True, "procent": 70.0},
    ]
    assert _srednia_ocen(oceny) == 85.0
