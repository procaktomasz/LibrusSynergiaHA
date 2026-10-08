"""Testy zdarzenia librus_apix_nowa_nieobecnosc - dane fikcyjne."""

from unittest.mock import MagicMock

from custom_components.librus_apix.sensor import (
    EVENT_NOWA_NIEOBECNOSC,
    LibrusDataUpdateCoordinator,
    _id_nieobecnosci,
)


def _lekcja(numer, przedmiot, obecnosc, opis=""):
    return {
        "data": "2026-10-05", "dzien_tygodnia": "pon.", "numer": numer, "przedmiot": przedmiot,
        "nauczyciel": "Kowalska Anna", "zastepca": "", "zastepstwo": False, "temat": "Temat",
        "obecnosc": obecnosc, "obecnosc_opis": opis,
    }


async def _zdarzenia(hass, poprzednie, obecne):
    coord = LibrusDataUpdateCoordinator(hass, MagicMock())
    coord._seen_absence_ids = {_id_nieobecnosci(l) for l in poprzednie}
    zebrane = []
    hass.bus.async_listen(EVENT_NOWA_NIEOBECNOSC, lambda e: zebrane.append(e.data))
    coord._fire_absence_events(obecne, "Jan Testowy")
    await hass.async_block_till_done()
    return zebrane


async def test_nowe_nb_i_sp_bez_obecnosci(hass):
    lekcje = [
        _lekcja(1, "Matematyka", "nb", "nieobecność"),
        _lekcja(2, "Fizyka", "sp", "spóźnienie"),
        _lekcja(3, "Chemia", "ob", "obecność"),
        _lekcja(4, "Historia", "wy", "wycieczka"),
        _lekcja(5, "Biologia", ""),
    ]
    zdarzenia = await _zdarzenia(hass, [], lekcje)
    zdarzenia.sort(key=lambda z: z["numer"])  # kolejność dostarczenia nie jest gwarantowana
    assert [(z["numer"], z["rodzaj"]) for z in zdarzenia] == [(1, "nb"), (2, "sp")]
    assert zdarzenia[0]["opis"] == "nieobecność"
    assert zdarzenia[0]["uczen"] == "Jan Testowy"


async def test_bez_powtorzen_i_usprawiedliwienie(hass):
    przed = [_lekcja(1, "Matematyka", "nb")]
    assert await _zdarzenia(hass, przed, przed) == []
    po = [_lekcja(1, "Matematyka", "u", "nieobecność uspr.")]
    (z,) = await _zdarzenia(hass, przed, po)
    assert z["rodzaj"] == "u"


async def test_zastepca_jako_nauczyciel(hass):
    lekcja = _lekcja(6, "Matematyka", "nb")
    lekcja.update(zastepstwo=True, zastepca="Nowak Jan")
    (z,) = await _zdarzenia(hass, [], [lekcja])
    assert z["nauczyciel"] == "Nowak Jan"
