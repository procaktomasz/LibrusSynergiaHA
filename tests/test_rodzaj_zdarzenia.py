"""Testy pola `rodzaj` w terminarzu - tytuły w formacie z Librusa, dane fikcyjne."""

import pytest

from custom_components.librus_apix.__init__ import _rodzaj_zdarzenia


@pytest.mark.parametrize(
    ("tytul", "href", "rodzaj"),
    [
        ("Nauczyciel: Kowalska Anna", "szczegoly_wolne/123", "nieobecnosc_nauczyciela"),
        ("Święto Niepodległości: SP", "szczegoly_wolne/124", "dzien_wolny"),
        ("Zastępstwo z Nowak Jan na lekcji nr: 2 (Matematyka)", "", "zastepstwo"),
        ("Jan Nowak na lekcji nr: 6 (Wychowanie fizyczne)", "", "zastepstwo"),
        ("Przesunięcie z Nowak Jan na lekcji nr: 7 (Historia)", "", "przesuniecie"),
        ("Odwołane zajęcia na lekcji nr: 3", "", "odwolanie"),
        ("sprawdzian", "szczegoly/1", "sprawdzian"),
        ("Praca klasowa", "szczegoly/2", "sprawdzian"),
        ("kartkówka", "szczegoly/3", "kartkowka"),
        ("wycieczka", "szczegoly/4", "wydarzenie"),
        ("", None, "wydarzenie"),
    ],
)
def test_rodzaj(tytul, href, rodzaj):
    assert _rodzaj_zdarzenia(tytul, href) == rodzaj
