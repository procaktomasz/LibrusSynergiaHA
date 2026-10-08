"""Testy opisu ocen tekstowych (pole `opis`) - dane fikcyjne w formacie desc z librus-apix."""

from custom_components.librus_apix.__init__ import _opis_oceny

KONIEC = "Kategoria: sprawdzian\nData: 2026-09-24 (czw.)\nNauczyciel: Kowalska Anna\nDodał: Kowalska Anna"


def test_procent():
    desc = f"Ocena: T\nPrzedmiot: Matematyka\nOcena: 45%\n{KONIEC}"
    assert _opis_oceny(desc) == "45%"


def test_opis_wielowierszowy():
    desc = f"Ocena: T\nPrzedmiot: Matematyka\nOcena: Diagnoza wstępna\n\n12/20p\n\n60%\n{KONIEC}"
    assert _opis_oceny(desc) == "Diagnoza wstępna · 12/20p · 60%"


def test_slowny_opis_i_np():
    desc = f"Ocena: T\nPrzedmiot: Język angielski\nOcena: aktywność na lekcjach\n{KONIEC}"
    assert _opis_oceny(desc) == "aktywność na lekcjach"
    desc = f"Ocena: np\nPrzedmiot: Język angielski\nOcena: nieprzygotowany\nKategoria: inna"
    assert _opis_oceny(desc) == "nieprzygotowany"


def test_zwykla_ocena_bez_opisu():
    assert _opis_oceny(f"Ocena: 5\nPrzedmiot: Fizyka\n{KONIEC}\nLicz do średniej: tak") == ""
    assert _opis_oceny("") == ""
    assert _opis_oceny(None) == ""
