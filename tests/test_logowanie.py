"""Testy ograniczania zapytan do Librusa przy bledach logowania i pobierania."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from librus_apix.exceptions import AuthorizationError, TokenError

from custom_components.librus_apix import LibrusApiClient
from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator


def _nieudany_new_client():
    lib = MagicMock()
    lib.get_token.side_effect = AuthorizationError("Nieprawidłowy login lub hasło")
    return lib


def _zalogowany_klient(hass=None) -> LibrusApiClient:
    client = LibrusApiClient("test_user", "test_pass", {}, hass=hass)
    client._client = MagicMock()
    client._token = "token"
    return client


# --- A1: blokada ponownego logowania po bledzie ---


async def test_nieudane_logowanie_blokuje_kolejne_proby():
    """Po nieudanym logowaniu kolejne proby nie wysylaja zapytan do Librusa."""
    client = LibrusApiClient("test_user", "test_pass")
    with patch("custom_components.librus_apix.new_client", side_effect=_nieudany_new_client) as nc:
        assert await client.async_authenticate() is False
        assert await client.async_authenticate() is False
        assert await client.async_authenticate() is False
    assert nc.call_count == 1


async def test_po_uplywie_blokady_ponowna_proba_i_dluzsza_blokada():
    """Po uplywie blokady logowanie jest ponawiane, a kolejna blokada jest dluzsza."""
    client = LibrusApiClient("test_user", "test_pass")
    teraz = [1000.0]
    with patch("custom_components.librus_apix.time.monotonic", side_effect=lambda: teraz[0]), \
         patch("custom_components.librus_apix.new_client", side_effect=_nieudany_new_client) as nc:
        assert await client.async_authenticate() is False
        pierwsza = client._auth_blocked_until - teraz[0]
        teraz[0] = client._auth_blocked_until + 1
        assert await client.async_authenticate() is False
        druga = client._auth_blocked_until - teraz[0]
    assert nc.call_count == 2
    assert druga == pierwsza * 2


async def test_blokada_ma_gorny_limit():
    """Blokada nie rosnie w nieskonczonosc."""
    client = LibrusApiClient("test_user", "test_pass")
    client._auth_failures = 50
    teraz = [1000.0]
    with patch("custom_components.librus_apix.time.monotonic", side_effect=lambda: teraz[0]), \
         patch("custom_components.librus_apix.new_client", side_effect=_nieudany_new_client):
        await client.async_authenticate()
    assert client._auth_blocked_until - teraz[0] == LibrusApiClient.AUTH_BACKOFF_MAX


async def test_udane_logowanie_zeruje_licznik_bledow():
    """Udane logowanie kasuje licznik bledow i blokade."""
    client = LibrusApiClient("test_user", "test_pass")
    client._auth_failures = 3
    client._auth_blocked_until = 0.0
    lib = MagicMock()
    lib.get_token.return_value = "token"
    with patch("custom_components.librus_apix.new_client", return_value=lib):
        assert await client.async_authenticate() is True
    assert client._auth_failures == 0
    assert client._auth_blocked_until == 0.0


def _mock_client_koordynatora():
    client = MagicMock(spec=LibrusApiClient)
    client.username = "test_user"
    client.options = {}
    client.async_authenticate = AsyncMock(return_value=False)
    for name in (
        "async_get_student_information", "async_get_grades", "async_get_behavior",
        "async_get_messages", "async_get_homework", "async_get_schedule",
        "async_get_timetable", "async_get_attendance", "async_get_announcements",
        "async_get_completed_lessons", "async_get_attendance_stats", "async_get_notes",
    ):
        setattr(client, name, AsyncMock(return_value=[]))
    return client


async def test_koordynator_przerywa_cykl_bez_logowania(hass):
    """Bez logowania i bez danych (pierwsze uruchomienie) koordynator zglasza UpdateFailed."""
    client = _mock_client_koordynatora()
    coord = LibrusDataUpdateCoordinator(hass, client)
    with pytest.raises(UpdateFailed):
        await coord._async_update_data()
    client.async_authenticate.assert_awaited_once()
    client.async_get_grades.assert_not_awaited()
    client.async_get_timetable.assert_not_awaited()


async def test_cykl_z_blednym_haslem_loguje_sie_raz(hass):
    """Caly cykl z blednym haslem to jedna proba logowania zamiast kilkunastu."""
    client = LibrusApiClient("test_user", "test_pass", {}, hass=hass)
    coord = LibrusDataUpdateCoordinator(hass, client)
    with patch("custom_components.librus_apix.new_client", side_effect=_nieudany_new_client) as nc:
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()
    assert nc.call_count == 1


DANE = {"oceny": [], "plan_lekcji": [], "student_info": None}


async def test_bez_logowania_z_danymi_encje_dostepne(hass):
    """Awaria logowania przy istniejacych danych: stare dane, encje dostepne, bez zapytan."""
    client = _mock_client_koordynatora()
    coord = LibrusDataUpdateCoordinator(hass, client)
    coord.async_set_updated_data(dict(DANE))
    poprzednie = coord.data

    await coord.async_refresh()

    assert coord.last_update_success is True
    assert coord.data is poprzednie
    client.async_authenticate.assert_awaited_once()
    client.async_get_grades.assert_not_awaited()
    client.async_get_timetable.assert_not_awaited()


async def test_bez_logowania_z_danymi_bez_zapisu_cache(hass):
    """Pominiety cykl nie zapisuje cache ani znacznika czasu pobrania."""
    client = _mock_client_koordynatora()
    coord = LibrusDataUpdateCoordinator(hass, client)
    coord.store = MagicMock()
    coord.store.async_save = AsyncMock()
    coord.meta_store = MagicMock()
    coord.meta_store.async_save = AsyncMock()
    coord.async_set_updated_data(dict(DANE))

    await coord.async_refresh()

    coord.store.async_save.assert_not_awaited()
    coord.meta_store.async_save.assert_not_awaited()


async def test_ostrzezenie_o_braku_logowania_raz_na_awarie(hass, caplog):
    """Przy kolejnych nieudanych cyklach ostrzezenie w logu tylko raz; po powrocie znow."""
    import logging

    client = _mock_client_koordynatora()
    coord = LibrusDataUpdateCoordinator(hass, client)
    coord.async_set_updated_data(dict(DANE))

    def _ostrzezenia():
        return [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "zalogować" in r.getMessage()
        ]

    with caplog.at_level(logging.WARNING, logger="custom_components.librus_apix"):
        await coord.async_refresh()
        await coord.async_refresh()
        await coord.async_refresh()
        assert len(_ostrzezenia()) == 1

        # Udane logowanie konczy awarie
        client.async_authenticate.return_value = True
        await coord.async_refresh()
        assert coord.last_update_success is True
        client.async_get_grades.assert_awaited()

        # Kolejna awaria - znowu jedno ostrzezenie
        client.async_authenticate.return_value = False
        await coord.async_refresh()
        await coord.async_refresh()
        assert len(_ostrzezenia()) == 2


# --- A2: ponawianie tylko po TokenError ---


async def test_blad_inny_niz_token_bez_ponowienia():
    """Blad parsowania/sieci nie powoduje drugiego zapytania w tym samym cyklu."""
    client = _zalogowany_klient()
    with patch("librus_apix.homework.get_homework", side_effect=RuntimeError("zepsuty HTML")) as gh:
        assert await client.async_get_homework() is None
    assert gh.call_count == 1


async def test_blad_planu_bez_ponowienia():
    """Blad w planie lekcji nie pobiera ponownie dwoch tygodni planu."""
    client = _zalogowany_klient()
    with patch("custom_components.librus_apix.plan_lekcji.get_timetable", side_effect=RuntimeError("zepsuty HTML")) as gt:
        assert await client.async_get_timetable() is None
    assert gt.call_count == 1


async def test_token_error_ponawia_po_zalogowaniu():
    """Wygasly token: ponowne logowanie i druga proba (jak dotad)."""
    client = _zalogowany_klient()

    async def _auth():
        client._client = MagicMock()
        client._token = "nowy"
        return True

    client.async_authenticate = AsyncMock(side_effect=_auth)
    with patch("librus_apix.homework.get_homework", side_effect=[TokenError("wygasl"), ["zadanie"]]) as gh:
        assert await client.async_get_homework() == ["zadanie"]
    assert gh.call_count == 2
    client.async_authenticate.assert_awaited_once()


# --- A3: zachowanie nie pobiera ocen drugi raz ---


async def test_zachowanie_nie_pobiera_ocen_ponownie_po_bledzie():
    """Gdy pobranie ocen zawiodlo, zachowanie nie wysyla kolejnego zapytania."""
    client = _zalogowany_klient()
    client._client.post.side_effect = RuntimeError("Librus nie odpowiada")
    assert await client.async_get_grades() is None
    assert await client.async_get_behavior() is None
    assert client._client.post.call_count == 1


async def test_zachowanie_po_resecie_logowania_zostaje():
    """Reset logowania (np. TokenError w innej metodzie) nie kasuje danych zachowania."""
    client = _zalogowany_klient()
    dane = {"punkty_startowe": 100}
    client._behavior_data = dane
    client._grades_attempted = True
    client._reset_auth()
    assert await client.async_get_behavior() == dane


async def test_zachowanie_bez_wczesniejszych_ocen_pobiera_oceny():
    """Samodzielne wywolanie (bez wczesniejszych ocen) nadal pobiera strone ocen."""
    client = _zalogowany_klient()

    async def _grades():
        client._grades_attempted = True
        client._behavior_data = {"punkty_startowe": 5}
        return []

    client.async_get_grades = AsyncMock(side_effect=_grades)
    assert await client.async_get_behavior() == {"punkty_startowe": 5}
    client.async_get_grades.assert_awaited_once()
