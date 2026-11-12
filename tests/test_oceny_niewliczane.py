"""#52 i oceny niewliczane do średniej: średnie bez procentów obok ocen 1-6, ukrywanie i znacznik "*"."""

from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.librus_apix import LibrusApiClient, _parse_point_grades
from custom_components.librus_apix.const import CONF_POKAZUJ_NIELICZONE
from custom_components.librus_apix.sensor import (
    EVENT_NOWA_OCENA,
    LibrusDataUpdateCoordinator,
    _srednia_ocen,
    _srednia_procent,
)

from test_oceny_punktowe import _a, _strona


# --- Średnie (#52) ---


def test_procent_obok_ocen_nie_psuje_sredniej():
    """#52: 68 (wynik procentowy) obok ocen 5 i 4 - średnia 4,5, a nie 25,67."""
    assert _srednia_ocen([{"ocena": "5"}, {"ocena": "4"}, {"ocena": "68"}]) == 4.5


@pytest.mark.parametrize("procent", ["68", "95%", "85 pkt", "85/100"])
def test_rozne_formy_procentow_poza_srednia_ocen(procent):
    assert _srednia_ocen([{"ocena": "5"}, {"ocena": procent}]) == 5.0


def test_same_procenty_jak_dotad():
    """Przedmiot wyłącznie z procentami: średnia z procentów, jak przed zmianą."""
    assert _srednia_ocen([{"ocena": "68"}, {"ocena": "95%"}]) == 81.5
    assert _srednia_ocen([
        {"ocena": "100", "punktowa": True, "procent": 100.0},
        {"ocena": "14", "punktowa": True, "procent": 70.0},
    ]) == 85.0


def test_ocena_niewliczana_poza_srednia():
    assert _srednia_ocen([{"ocena": "5"}, {"ocena": "2*", "liczona": False}, {"ocena": "4"}]) == 4.5
    assert _srednia_ocen([{"ocena": "2", "liczona": False}]) is None


def test_srednia_procent():
    assert _srednia_procent([{"ocena": "5"}, {"ocena": "68"}, {"ocena": "90%"}]) == 79.0
    assert _srednia_procent([{"ocena": "5"}, {"ocena": "4+"}]) is None
    assert _srednia_procent([{"ocena": "60", "liczona": False}, {"ocena": "80"}]) == 80.0


def test_srednia_z_plusami_i_minusami_bez_zmian():
    assert _srednia_ocen([{"ocena": "5+"}, {"ocena": "4-"}]) == 4.62


# --- Atrybuty ocen z biblioteki ---


def _ocena(wartosc, desc_extra="", waga=1, data="2026-10-09"):
    return SimpleNamespace(
        title="język angielski", grade=wartosc, date=data, category="Kartkówka", teacher="Czarnecka Karolina",
        semester=1, comments=None, weight=waga, counts=False,
        desc=f"Ocena: {wartosc}\nPrzedmiot: język angielski\nKategoria: Kartkówka\n{desc_extra}",
    )


def _sem(slownik):
    d = defaultdict(list)
    d.update(slownik)
    return [d, defaultdict(list)]


async def _oceny_z_biblioteki(oceny, punktowe=None):
    client = LibrusApiClient("u", "p")
    client._client = MagicMock()
    client._token = "token"
    client._client.post.return_value.text = '<table class="decorated"><tr class="line0"><td>x</td></tr></table>'
    with patch("custom_components.librus_apix._current_semester", return_value=1), \
         patch("librus_apix.grades._extract_grades_numeric", return_value=(_sem({"język angielski": oceny}), [])), \
         patch("librus_apix.grades._extract_grades_descriptive", return_value=_sem({})), \
         patch("custom_components.librus_apix._parse_point_grades", return_value=punktowe or []):
        return await client.async_get_grades()


async def test_atrybuty_oceny_niewliczanej_i_poprawy():
    oceny = await _oceny_z_biblioteki([
        _ocena("2", "Licz do średniej: nie\nKomentarz: narrative tenses\n", waga=0),
        _ocena("4", "Licz do średniej: tak\nWaga: 1\nPoprawa oceny: 2 (Poprawa)\n", data="2026-10-24"),
    ])
    poprawiona, poprawa = oceny
    assert poprawiona["liczona"] is False
    assert poprawiona["poprawa_oceny"] == ""
    assert poprawa["liczona"] is True
    assert poprawa["waga"] == 1
    assert poprawa["poprawa_oceny"] == "2 (Poprawa)"


async def test_brak_informacji_o_liczeniu_to_ocena_liczona():
    """Biblioteka zwraca counts=False, gdy w opisie nie ma linii "Licz do średniej" - nie ukrywamy takiej oceny."""
    (ocena,) = await _oceny_z_biblioteki([_ocena("5")])
    assert ocena["liczona"] is True


def test_ocena_punktowa_niewliczana():
    html = _strona(
        '<tr class="line0"><td class="center micro screen-only"><img id="przedmioty_OP_1_node"></td>'
        "<td>Fizyka</td><td>"
        + _a("Kartkówka (0-100)", "2026-10-19 (pn.)", 1, "99").replace("Licz do wyniku: TAK", "Licz do wyniku: NIE")
        + _a("Test (0-100)", "2026-10-20 (wt.)", 2, "100")
        + '</td><td class="center"> - </td><td>Brak ocen</td><td> - </td><td> - </td></tr>'
    )
    p99, p100 = _parse_point_grades(html)
    assert p99["liczona"] is False
    assert p100["liczona"] is True


# --- Koordynator: ukrywanie / znacznik "*" ---


def _koordynator(hass, grades, pokazuj=None):
    client = MagicMock(spec=LibrusApiClient)
    client.username = "u"
    client.options = {} if pokazuj is None else {CONF_POKAZUJ_NIELICZONE: pokazuj}
    client._client = MagicMock()
    client._token = "token"
    client.async_get_grades = AsyncMock(return_value=grades)
    for name in ("async_get_student_information", "async_get_attendance_stats", "async_get_behavior"):
        setattr(client, name, AsyncMock(return_value=None))
    for name in ("async_get_messages", "async_get_homework", "async_get_schedule", "async_get_timetable",
                 "async_get_attendance", "async_get_announcements", "async_get_completed_lessons", "async_get_notes"):
        setattr(client, name, AsyncMock(return_value=[]))
    return LibrusDataUpdateCoordinator(hass, client)


def _g(ocena, liczona=True, data="2026-10-24", poprawa="", flaga=None, przedmiot="język angielski"):
    """Ocena jak z async_get_grades; flaga_sredniej domyślnie zgodna z `liczona` ("tak"/"nie")."""
    return {"subject": przedmiot, "grade": ocena, "date": data, "category": "Kartkówka",
            "teacher": "Czarnecka Karolina", "semester": 1, "komentarz": "", "opis": "", "type": "numeric",
            "liczona": liczona, "waga": 1, "poprawa_oceny": poprawa,
            "flaga_sredniej": flaga if flaga is not None else ("tak" if liczona else "nie")}


OCENY = [_g("2-", data="2026-10-01"), _g("2", liczona=False, data="2026-10-09"), _g("4", poprawa="2 (Poprawa)")]


async def test_domyslnie_ukrywa_oceny_niewliczane(hass):
    data = await _koordynator(hass, OCENY)._async_update_data()
    lista = data["oceny_wg_przedmiotu"]["język angielski"]
    assert [o["ocena"] for o in lista] == ["2-", "4"]
    assert len(data["oceny"]) == 2
    assert lista[1]["poprawa_oceny"] == "2 (Poprawa)"
    assert all(o["liczona"] for o in lista)


async def test_opcja_pokazuje_niewliczane_z_gwiazdka(hass):
    data = await _koordynator(hass, OCENY, pokazuj=True)._async_update_data()
    lista = data["oceny_wg_przedmiotu"]["język angielski"]
    assert [o["ocena"] for o in lista] == ["2-", "2*", "4"]
    assert lista[1]["liczona"] is False
    assert _srednia_ocen(lista) == 2.88  # (1.75 + 4) / 2 - "2*" poza średnią


async def test_zdarzenia_dla_ocen_niewliczanych(hass):
    """Ukryta ocena nie wysyła zdarzenia; pokazana - z oryginalną wartością i liczona: false."""
    for pokazuj, oczekiwane in ((False, ["2-", "4"]), (True, ["2-", "2", "4"])):
        koord = _koordynator(hass, [], pokazuj=pokazuj)
        await koord._async_update_data()  # pierwszy cykl bez zdarzeń
        koord.client.async_get_grades.return_value = OCENY
        zdarzenia = []
        hass.bus.async_listen(EVENT_NOWA_OCENA, lambda e, z=zdarzenia: z.append(e.data))
        await koord._async_update_data()
        await hass.async_block_till_done()
        # Kolejność dostarczania zdarzeń nie jest gwarantowana
        assert sorted(z["ocena"] for z in zdarzenia) == sorted(oczekiwane)
        if pokazuj:
            assert {z["ocena"]: z["liczona"] for z in zdarzenia} == {"2-": True, "2": False, "4": True}


async def test_stary_cache_bez_pola_liczona(hass):
    """Oceny z cache sprzed zmiany (bez "liczona") traktujemy jak liczone."""
    stara = {k: v for k, v in _g("5").items() if k not in ("liczona", "waga", "poprawa_oceny")}
    data = await _koordynator(hass, [stara])._async_update_data()
    (o,) = data["oceny_wg_przedmiotu"]["język angielski"]
    assert o["ocena"] == "5" and o["liczona"] is True


# --- Zmiana opcji działa od razu, z cache, bez pytania Librusa ---


def _cache_z_ocenami():
    """Cache zapisany przy wyłączonej opcji: widoczne bez "2", ale w oceny_wszystkie są wszystkie."""
    return {
        "plan_lekcji": [],
        "oceny": [OCENY[0], OCENY[2]],
        "oceny_wg_przedmiotu": {"język angielski": [{"ocena": "2-"}, {"ocena": "4"}]},
        "oceny_wszystkie": list(OCENY),
        "student_info": None,
    }


async def _wczytaj_z_cache(hass, pokazuj):
    koord = _koordynator(hass, [], pokazuj=pokazuj)
    koord.store = MagicMock()
    koord.store.async_load = AsyncMock(return_value=_cache_z_ocenami())
    koord.meta_store = MagicMock()
    koord.meta_store.async_load = AsyncMock(return_value=None)
    return koord, await koord.async_load_cached_data()


async def test_wlaczenie_opcji_dziala_od_razu_z_cache(hass):
    koord, dane = await _wczytaj_z_cache(hass, pokazuj=True)
    assert [o["ocena"] for o in dane["oceny_wg_przedmiotu"]["język angielski"]] == ["2-", "2*", "4"]
    assert len(dane["oceny"]) == 3
    koord.client.async_get_grades.assert_not_awaited()


async def test_wylaczenie_opcji_dziala_od_razu_z_cache(hass):
    zapisany = _cache_z_ocenami()
    zapisany["oceny_wg_przedmiotu"] = {"język angielski": [{"ocena": "2-"}, {"ocena": "2*"}, {"ocena": "4"}]}
    koord = _koordynator(hass, [], pokazuj=False)
    koord.store = MagicMock()
    koord.store.async_load = AsyncMock(return_value=zapisany)
    koord.meta_store = MagicMock()
    koord.meta_store.async_load = AsyncMock(return_value=None)
    dane = await koord.async_load_cached_data()
    assert [o["ocena"] for o in dane["oceny_wg_przedmiotu"]["język angielski"]] == ["2-", "4"]
    koord.client.async_get_grades.assert_not_awaited()


async def test_stary_cache_bez_oceny_wszystkie_bez_zmian(hass):
    """Cache sprzed zmiany (bez oceny_wszystkie) zostaje jak był - poprawi się przy pobraniu."""
    zapisany = _cache_z_ocenami()
    del zapisany["oceny_wszystkie"]
    koord = _koordynator(hass, [], pokazuj=True)
    koord.store = MagicMock()
    koord.store.async_load = AsyncMock(return_value=zapisany)
    koord.meta_store = MagicMock()
    koord.meta_store.async_load = AsyncMock(return_value=None)
    dane = await koord.async_load_cached_data()
    assert [o["ocena"] for o in dane["oceny_wg_przedmiotu"]["język angielski"]] == ["2-", "4"]


async def test_cache_zapisuje_wszystkie_oceny(hass):
    """Do danych i cache trafiają też oceny ukryte - żeby zmiana opcji mogła je pokazać."""
    data = await _koordynator(hass, OCENY, pokazuj=False)._async_update_data()
    assert [g["grade"] for g in data["oceny_wszystkie"]] == ["2-", "2", "4"]
    assert [g["grade"] for g in data["oceny"]] == ["2-", "4"]


async def test_wlaczenie_opcji_nie_wysyla_zdarzen_o_starych_ocenach(hass):
    """Po włączeniu opcji (start z cache) wcześniej ukryte oceny nie są zgłaszane jako nowe."""
    koord, dane = await _wczytaj_z_cache(hass, pokazuj=True)
    koord.seed_seen_from_cached_data(dane)
    koord.data = dane
    koord.client.async_get_grades.return_value = list(OCENY)
    zdarzenia = []
    hass.bus.async_listen(EVENT_NOWA_OCENA, lambda e: zdarzenia.append(e.data))
    await koord._async_update_data()
    await hass.async_block_till_done()
    assert zdarzenia == []


async def test_brak_pobranych_ocen_uzywa_wszystkich_z_poprzedniego_stanu(hass):
    """Błąd pobrania ocen: poprzedni stan (wszystkie oceny) z bieżącym ustawieniem opcji."""
    koord = _koordynator(hass, None, pokazuj=True)
    koord.data = {"oceny": [], "oceny_wszystkie": list(OCENY), "plan_lekcji": []}
    data = await koord._async_update_data()
    assert [o["ocena"] for o in data["oceny_wg_przedmiotu"]["język angielski"]] == ["2-", "2*", "4"]


# --- #55 / #58: flaga "Licz do średniej" tylko w przedmiotach, które jej używają ---


@pytest.mark.parametrize("linia,flaga,liczona", [
    ("Licz do średniej: tak\n", "tak", True),
    ("Licz do średniej: nie\n", "nie", False),
    ("", "", True),
    # Tytuł z <br/>: biblioteka skleja linie bez znaku nowej linii
    ("Licz do średniej: takWaga: 1\n", "tak", True),
    ("Licz do średniej: nieWaga: 0\n", "nie", False),
])
async def test_flaga_sredniej_z_opisu(linia, flaga, liczona):
    (ocena,) = await _oceny_z_biblioteki([_ocena("5", linia)])
    assert ocena["flaga_sredniej"] == flaga
    assert ocena["liczona"] is liczona


async def test_58_przedmiot_bez_ocen_tak_pokazuje_wszystkie(hass):
    """#58: wszystkie oceny z angielskiego mają "Licz do średniej: nie" - widoczne, bez "*", w średniej."""
    oceny = [_g("6", liczona=False, data=f"2026-09-2{i}") for i in range(5)] + [
        _g("5", flaga="", przedmiot="Edukacja matematyczna"),
    ]
    data = await _koordynator(hass, oceny)._async_update_data()
    angielski = data["oceny_wg_przedmiotu"]["język angielski"]
    assert [o["ocena"] for o in angielski] == ["6"] * 5
    assert all(o["liczona"] for o in angielski)
    assert _srednia_ocen(angielski) == 6.0
    assert len(data["oceny"]) == 6


async def test_55_ocena_nie_obok_wpisu_bez_flagi(hass):
    """#55: WF z oceną "5" ("nie") i wpisem "-" bez flagi - przedmiot nie używa flagi, oba widoczne."""
    oceny = [_g("5", liczona=False, przedmiot="WYCHOWANIE FIZYCZNE"),
             _g("-", flaga="", przedmiot="WYCHOWANIE FIZYCZNE", data="2026-10-28")]
    data = await _koordynator(hass, oceny)._async_update_data()
    wf = data["oceny_wg_przedmiotu"]["WYCHOWANIE FIZYCZNE"]
    assert [o["ocena"] for o in wf] == ["5", "-"]
    assert wf[0]["liczona"] is True


async def test_flaga_dziala_niezaleznie_w_kazdym_przedmiocie(hass):
    """Angielski używa flagi (poprawiona "2" ukryta), historia nie (ocena "nie" widoczna)."""
    oceny = list(OCENY) + [_g("3", liczona=False, przedmiot="historia")]
    data = await _koordynator(hass, oceny)._async_update_data()
    assert [o["ocena"] for o in data["oceny_wg_przedmiotu"]["język angielski"]] == ["2-", "4"]
    assert [o["ocena"] for o in data["oceny_wg_przedmiotu"]["historia"]] == ["3"]


async def test_cache_z_305_bez_flagi_pokazuje_oceny(hass):
    """Cache z 3.0.5 (liczona: false, bez flaga_sredniej) - oceny widoczne do najbliższego pobrania."""
    stare = [{k: v for k, v in g.items() if k != "flaga_sredniej"} for g in OCENY]
    koord = _koordynator(hass, [], pokazuj=False)
    koord.store = MagicMock()
    koord.store.async_load = AsyncMock(return_value={"plan_lekcji": [], "oceny": [], "oceny_wszystkie": stare,
                                                     "oceny_wg_przedmiotu": {}, "student_info": None})
    koord.meta_store = MagicMock()
    koord.meta_store.async_load = AsyncMock(return_value=None)
    dane = await koord.async_load_cached_data()
    assert [o["ocena"] for o in dane["oceny_wg_przedmiotu"]["język angielski"]] == ["2-", "2", "4"]


def test_flaga_oceny_punktowej():
    html = _strona(
        '<tr class="line0"><td class="center micro screen-only"><img id="przedmioty_OP_1_node"></td>'
        "<td>Fizyka</td><td>"
        + _a("Kartkówka (0-100)", "2026-10-19 (pn.)", 1, "99").replace("Licz do wyniku: TAK", "Licz do wyniku: NIE")
        + _a("Test (0-100)", "2026-10-20 (wt.)", 2, "100")
        + '</td><td class="center"> - </td><td>Brak ocen</td><td> - </td><td> - </td></tr>'
    )
    p99, p100 = _parse_point_grades(html)
    assert (p99["flaga_sredniej"], p100["flaga_sredniej"]) == ("nie", "tak")


# --- Opcja w ustawieniach ---


async def test_opcja_w_ustawieniach(hass):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    from custom_components.librus_apix.const import DOMAIN

    entry = MockConfigEntry(domain=DOMAIN, data={"username": "u", "password": "p"}, options={})
    entry.add_to_hass(hass)
    wynik = await hass.config_entries.options.async_init(entry.entry_id)
    klucze = [str(k) for k in wynik["data_schema"].schema]
    assert CONF_POKAZUJ_NIELICZONE in klucze
    domyslna = next(k for k in wynik["data_schema"].schema if str(k) == CONF_POKAZUJ_NIELICZONE).default()
    assert domyslna is False
