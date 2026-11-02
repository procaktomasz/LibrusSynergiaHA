"""Szczegoly i przedmiot wpisow terminarza (#53) - dane fikcyjne w formacie z Librusa."""

from librus_apix.schedule import _parse_title_into_pairs

from custom_components.librus_apix.__init__ import (
    LibrusApiClient,
    _przedmiot_zdarzenia,
    _szczegoly_zdarzenia,
)
from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator
from tests.test_plan_fuzja import _klient_planu, _lekcja


def test_wpis_bez_opisu_nie_ma_unknown():
    """Domyslny tytul biblioteki ("Nauczyciel: unknown<br />Opis: unknown") daje puste szczegoly."""
    dane = _parse_title_into_pairs("Nauczyciel: unknown<br />Opis: unknown")
    assert _szczegoly_zdarzenia(dane) == {}


def test_wpis_z_nauczycielem_i_opisem_bez_zmian():
    dane = {"Nauczyciel": "Nowak Jan", "Opis": "Dzial 1", "Data dodania": "2026-10-19 14:37:53"}
    assert _szczegoly_zdarzenia(dane) == dane


def test_nauczyciel_bez_opisu_i_opis_bez_nauczyciela():
    assert _szczegoly_zdarzenia({"Nauczyciel": "Nowak Jan", "Opis": "unknown"}) == {"Nauczyciel": "Nowak Jan"}
    assert _szczegoly_zdarzenia({"Nauczyciel": "unknown", "Opis": "Dzial 2"}) == {"Opis": "Dzial 2"}


def test_wieloliniowy_opis_zachowany():
    """Linia opisu bez dwukropka ("unknown") i linia "klucz: wartosc" dopisuja sie do opisu."""
    dane = _parse_title_into_pairs("Nauczyciel: Nowak Jan<br />Opis: Materialy<br />Olowek, kredki<br />Str: 86")
    assert _szczegoly_zdarzenia(dane) == {"Nauczyciel": "Nowak Jan", "Opis": "Materialy\nOlowek, kredki\nStr: 86"}


def test_brak_danych():
    assert _szczegoly_zdarzenia(None) == {}
    assert _szczegoly_zdarzenia({}) == {}


def test_przedmiot_bez_powtorzonego_tytulu():
    tytul = "Zastępstwo z Nowak Jan na lekcji nr: 4 (wychowanie fizyczne)"
    assert _przedmiot_zdarzenia(tytul, tytul) == ""
    assert _przedmiot_zdarzenia("Fizyka", "sprawdzian") == "Fizyka"
    assert _przedmiot_zdarzenia("Odwołane zajęcia ", "Kowalska Anna na lekcji nr: 6") == "Odwołane zajęcia"
    assert _przedmiot_zdarzenia(None, None) == ""


async def test_zastepstwo_bez_przedmiotu_nadal_trafia_na_lekcje_z_numeru(hass):
    """Pusty `przedmiot` zastepstwa nie psuje dopasowania do planu (nazwa jest w tytule)."""
    plan = [{"dzien_tygodnia": "Środa", "data": "2026-10-21", "lekcje": [
        dict(_lekcja(1, "08:00", "08:45"), przedmiot="Język polski", data="2026-10-21"),
        dict(_lekcja(2, "08:55", "09:40"), przedmiot="Biologia", data="2026-10-21"),
        dict(_lekcja(3, "09:50", "10:35"), przedmiot="Historia", data="2026-10-21"),
    ]}]
    tytul = "Zastępstwo z Nowak Jan na lekcji nr: 2 (Biologia)"
    terminarz = [{"data": "2026-10-21", "tydzien": "Środa", "tytul": tytul, "rodzaj": "zastepstwo",
                  "przedmiot": "", "godzina": "unknown", "numer_lekcji": 2, "szczegoly": {}, "href": ""}]
    data = await LibrusDataUpdateCoordinator(hass, _klient_planu(plan, terminarz))._async_update_data()
    lekcje = data["plan_lekcji"][0]["lekcje"]
    assert [l["numer"] for l in lekcje] == [1, 2, 3]
    assert lekcje[1]["zdarzenie"] == tytul
    assert lekcje[0]["zdarzenie"] is None


_HTML = """
<html><body><div class="kalendarz-dzien"><div class="kalendarz-numer-dnia">28</div>
<table>
<tr><td>Zastępstwo z Nowak Jan na lekcji nr: 4 (wychowanie fizyczne)</td></tr>
<tr><td title="Nauczyciel: Kowalska Anna<br />Opis: Dzial 1" onclick="location.href='/terminarz/szczegoly/7'"><span>Fizyka</span><br />sprawdzian</td></tr>
</table></div></body></html>
"""


async def test_terminarz_z_prawdziwym_parserem_biblioteki():
    """Wpis zastepstwa z HTML-a Librusa: bez "unknown\\nOpis" i bez powtorzonego tytulu."""
    from unittest.mock import MagicMock

    from custom_components.librus_apix import LibrusApiClient

    client = LibrusApiClient("uczen", "haslo")
    client._client = MagicMock()
    client._client.SCHEDULE_URL = "https://librus.invalid/terminarz/"
    client._client.post.return_value.text = _HTML
    client._token = "token"
    wpisy = await client.async_get_schedule()

    zast = next(w for w in wpisy if w["rodzaj"] == "zastepstwo")
    assert zast["tytul"] == "Zastępstwo z Nowak Jan na lekcji nr: 4 (wychowanie fizyczne)"
    assert zast["przedmiot"] == ""
    assert zast["numer_lekcji"] == 4
    assert zast["szczegoly"] == {}

    spr = next(w for w in wpisy if w["rodzaj"] == "sprawdzian")
    assert spr["przedmiot"] == "Fizyka"
    assert spr["szczegoly"] == {"Nauczyciel": "Kowalska Anna", "Opis": "Dzial 1"}


def test_wpis_z_dawnym_przedmiotem_nie_jest_nowym_zdarzeniem():
    """Po aktualizacji (przedmiot == tytul -> pusty) znane wpisy nie wysylaja ponownie zdarzenia."""
    from unittest.mock import MagicMock

    client = MagicMock(spec=LibrusApiClient)
    client.username = "u"
    client.options = {}
    coord = LibrusDataUpdateCoordinator(MagicMock(), client)
    coord.hass = MagicMock()
    coord._seen_schedule_ids.add(("2026-12-24", "Przerwa swiateczna: SP", "Przerwa swiateczna: SP"))

    wpisy = [
        {"data": "2026-12-24", "tytul": "Przerwa swiateczna: SP", "przedmiot": "", "godzina": "unknown"},
        {"data": "2026-12-25", "tytul": "Nowy wpis", "przedmiot": "", "godzina": "unknown"},
    ]
    coord._fire_schedule_events(wpisy, "Jan")
    assert coord.hass.bus.async_fire.call_count == 1
    assert coord.hass.bus.async_fire.call_args.args[1]["tytul"] == "Nowy wpis"

    coord.hass.bus.async_fire.reset_mock()
    coord._fire_schedule_events(wpisy, "Jan")  # drugi cykl: nic nowego
    coord.hass.bus.async_fire.assert_not_called()
