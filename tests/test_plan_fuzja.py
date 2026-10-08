"""Fuzja terminarza z planem lekcji: brak sztucznych lekcji dla nieobecności nauczyciela."""

from unittest.mock import AsyncMock, MagicMock

from custom_components.librus_apix.__init__ import LibrusApiClient
from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator


def _lekcja(nr, od, do):
    return {
        "przedmiot": "Matematyka", "nauczyciel_i_sala": "Kowalska Anna s. 12", "godzina_od": od,
        "godzina_do": do, "data": "2026-10-07", "numer": nr, "zdarzenie": None,
        "odwolana": False, "zastepstwo": False, "nauczyciel": "Kowalska Anna", "sala": "s. 12",
    }


def _wpis(tytul, nr, rodzaj):
    return {"data": "2026-10-07", "tydzien": "Środa", "tytul": tytul, "rodzaj": rodzaj, "przedmiot": "Historia",
            "godzina": "unknown", "numer_lekcji": nr, "szczegoly": {}, "href": ""}


async def test_bez_sztucznej_lekcji_dla_nieobecnosci_nauczyciela(hass):
    client = MagicMock(spec=LibrusApiClient)
    client.options = {}
    for name in ("async_get_student_information", "async_get_grades", "async_get_messages", "async_get_homework",
                 "async_get_attendance", "async_get_announcements", "async_get_completed_lessons"):
        setattr(client, name, AsyncMock(return_value=[]))
    client.async_get_attendance_stats = AsyncMock(return_value=None)
    client.async_get_timetable = AsyncMock(return_value=[
        {"dzien_tygodnia": "Środa", "data": "2026-10-07",
         "lekcje": [_lekcja(1, "08:00", "08:45"), _lekcja(2, "08:55", "09:40")]},
    ])
    client.async_get_schedule = AsyncMock(return_value=[
        _wpis("Nauczyciel: Nowak Jan", "8", "nieobecnosc_nauczyciela"),
        _wpis("poprawa", "9", "wydarzenie"),
    ])
    data = await LibrusDataUpdateCoordinator(hass, client)._async_update_data()
    lekcje = data["plan_lekcji"][0]["lekcje"]
    assert [l["numer"] for l in lekcje] == [1, 2, 9]  # 8 (nieobecność nauczyciela) pominięta
    for l in lekcje:
        assert {"sala", "nauczyciel", "odwolana", "zastepstwo", "zdarzenie"} <= set(l)
