"""Testy pobierania wiadomości (opcja fetch_messages_count, stronicowanie skrzynki)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.librus_apix.__init__ import LibrusApiClient
from custom_components.librus_apix.sensor import LibrusWiadomosciSensor


def _msg(i):
    return SimpleNamespace(
        author="Nauczyciel Testowy", title=f"Wiadomość {i}", date="2026-10-01 10:00:00",
        href=f"/wiadomosci/1/5/{i}", unread=False, has_attachment=False,
    )


def _skrzynka(rozmiar_strony, wszystkich):
    """get_received jak w Librusie: dla strony poza zakresem zwraca ostatnią stronę."""
    ostatnia = max((wszystkich - 1) // rozmiar_strony, 0)

    def get_received(_client, page):
        page = min(page, ostatnia)
        start = page * rozmiar_strony
        return [_msg(i) for i in range(start, min(start + rozmiar_strony, wszystkich))]
    return MagicMock(side_effect=get_received)


async def _pobierz(get_received, count):
    client = LibrusApiClient("user", "pass", {})
    client._client = MagicMock()
    client._token = "token"
    with patch("librus_apix.messages.get_received", get_received):
        return await client.async_get_messages(count=count)


@pytest.mark.asyncio
async def test_mala_skrzynka_bez_duplikatow():
    get_received = _skrzynka(50, 11)
    result = await _pobierz(get_received, 25)
    assert len(result) == 11
    assert len({m["href"] for m in result}) == 11
    assert get_received.call_count == 2  # druga strona = powtórzona pierwsza -> koniec


@pytest.mark.asyncio
async def test_kilka_stron():
    get_received = _skrzynka(10, 51)
    result = await _pobierz(get_received, 25)
    assert len(result) == 25
    assert len({m["href"] for m in result}) == 25
    assert get_received.call_count == 3


@pytest.mark.asyncio
async def test_pusta_skrzynka():
    result = await _pobierz(MagicMock(return_value=[]), 10)
    assert result == []


def _sensor(liczba):
    coordinator = MagicMock()
    coordinator.data = {"wiadomosci": [
        {"author": "A", "title": f"T{i}", "date": "2026-10-01", "unread": i < 3} for i in range(liczba)
    ]}
    return LibrusWiadomosciSensor(coordinator, MagicMock(entry_id="e1", options={}))


def test_atrybut_zawiera_wszystkie_pobrane():
    attrs = _sensor(25).extra_state_attributes
    assert len(attrs["wiadomosci"]) == 25
    assert attrs["wiadomosci"][24]["temat"] == "T24"


def test_atrybut_dopelniony_do_5():
    attrs = _sensor(2).extra_state_attributes
    assert len(attrs["wiadomosci"]) == 5  # szablony kart oczekują min. 5 pozycji
    assert attrs["wiadomosci"][4]["temat"] == "Brak"


@pytest.mark.asyncio
async def test_wiadomosci_z_cache():
    """Wiadomości obecne w cache otrzymują od razu treść."""
    client = LibrusApiClient("user", "pass", {})
    client._client = MagicMock()
    client._token = "token"
    client._message_cache["/wiadomosci/1/5/0"] = "Zapisana treść"

    get_received = _skrzynka(10, 2)
    with patch("librus_apix.messages.get_received", get_received):
        res = await client.async_get_messages(count=2)
    assert res[0]["content"] == "Zapisana treść"
    assert res[1]["content"] is None  # brak w cache -> None na starcie


@pytest.mark.asyncio
async def test_init_i_save_cache():
    """Test inicjalizacji i zapisu trwałego cache."""
    from unittest.mock import AsyncMock
    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={"/msg/1": "Treść 1"})
    mock_store.async_save = AsyncMock()

    client = LibrusApiClient("user", "pass", {})
    client._store = mock_store

    await client.async_init_cache()
    assert client._message_cache["/msg/1"] == "Treść 1"

    client._message_cache["/msg/2"] = "Treść 2"
    await client.async_save_cache()
    mock_store.async_save.assert_called_once_with(client._message_cache)


def test_sensor_pusta_tresc_jako_pusty_string():
    """Gdy treść wiadomości to None, sensor wystawia pusty string zamiast None."""
    coordinator = MagicMock()
    coordinator.data = {"wiadomosci": [
        {"author": "Nauczyciel", "title": "Temat", "date": "2026-10-01", "unread": False, "content": None}
    ]}
    sensor = LibrusWiadomosciSensor(coordinator, MagicMock(entry_id="e1", options={}))
    attrs = sensor.extra_state_attributes
    assert attrs["wiadomosci"][0]["tresc"] == ""


@pytest.mark.asyncio
async def test_service_get_message_single_student(hass):
    """Test usługi get_message dla pojedynczego ucznia ze zwracaniem odpowiedzi."""
    from custom_components.librus_apix import async_setup
    from custom_components.librus_apix.const import DOMAIN

    client = MagicMock(spec=LibrusApiClient)
    client._client = MagicMock()
    client._token = "token"
    client._message_cache = {}
    client.coordinator = MagicMock()
    client.coordinator.data = {"wiadomosci": [{"href": "/wiadomosci/1"}]}

    await async_setup(hass, {})
    hass.data[DOMAIN]["entry_1"] = client

    with patch("librus_apix.messages.message_content") as mock_mc:
        msg_obj = SimpleNamespace(content="Treść pobranej wiadomości")
        mock_mc.return_value = msg_obj

        events = []
        hass.bus.async_listen(f"{DOMAIN}_message_read", lambda ev: events.append(ev))

        response = await hass.services.async_call(
            DOMAIN,
            "get_message",
            {"url": "/wiadomosci/1"},
            blocking=True,
            return_response=True,
        )
        await hass.async_block_till_done()

        assert response == {"content": "Treść pobranej wiadomości"}
        mock_mc.assert_called_once_with(client._client, "/wiadomosci/1")
        assert len(events) == 1
        assert events[0].data["content"] == "Treść pobranej wiadomości"
        assert events[0].data["url"] == "/wiadomosci/1"


@pytest.mark.asyncio
async def test_service_get_message_multi_student_by_url(hass):
    """Test wyboru właściwego klienta przy wielu uczniach na podstawie dopasowania URL."""
    from custom_components.librus_apix import async_setup
    from custom_components.librus_apix.const import DOMAIN

    client_a = MagicMock(spec=LibrusApiClient)
    client_a._client = MagicMock()
    client_a._token = "token_a"
    client_a._message_cache = {}
    client_a.coordinator = MagicMock()
    client_a.coordinator.data = {"wiadomosci": [{"href": "/msg/a1"}]}

    client_b = MagicMock(spec=LibrusApiClient)
    client_b._client = MagicMock()
    client_b._token = "token_b"
    client_b._message_cache = {}
    client_b.coordinator = MagicMock()
    client_b.coordinator.data = {"wiadomosci": [{"href": "/msg/b1"}]}

    await async_setup(hass, {})
    # Rejestrujemy najpierw klienta A, a potem klienta B
    hass.data[DOMAIN]["entry_a"] = client_a
    hass.data[DOMAIN]["entry_b"] = client_b

    with patch("librus_apix.messages.message_content") as mock_mc:
        mock_mc.return_value = SimpleNamespace(content="Treść z konta B")

        # Pobieramy wiadomość należącą do dziecka B
        response = await hass.services.async_call(
            DOMAIN,
            "get_message",
            {"url": "/msg/b1"},
            blocking=True,
            return_response=True,
        )

        assert response == {"content": "Treść z konta B"}
        # Upewniamy się, że wywołano klienta B, a NIE klienta A!
        mock_mc.assert_called_once_with(client_b._client, "/msg/b1")


@pytest.mark.asyncio
async def test_service_get_message_multi_student_by_entity_id(hass):
    """Test wyboru właściwego klienta przy wielu uczniach na podstawie parametru entity_id."""
    from custom_components.librus_apix import async_setup
    from custom_components.librus_apix.const import DOMAIN

    client_a = MagicMock(spec=LibrusApiClient)
    client_a._client = MagicMock()
    client_a._token = "token_a"

    client_b = MagicMock(spec=LibrusApiClient)
    client_b._client = MagicMock()
    client_b._token = "token_b"

    await async_setup(hass, {})
    hass.data[DOMAIN]["entry_a"] = client_a
    hass.data[DOMAIN]["entry_b"] = client_b

    mock_entry = SimpleNamespace(config_entry_id="entry_b")
    with patch("homeassistant.helpers.entity_registry.EntityRegistry.async_get", return_value=mock_entry):
        with patch("librus_apix.messages.message_content") as mock_mc:
            mock_mc.return_value = SimpleNamespace(content="Treść z konta B przez entity_id")

            response = await hass.services.async_call(
                DOMAIN,
                "get_message",
                {"url": "/msg/unknown", "entity_id": "sensor.librus_b_wiadomosci"},
                blocking=True,
                return_response=True,
            )

            assert response == {"content": "Treść z konta B przez entity_id"}
            mock_mc.assert_called_once_with(client_b._client, "/msg/unknown")


@pytest.mark.asyncio
async def test_background_fetcher_session_lock_synchronization(hass):
    """Test weryfikujący, że zadanie w tle synchronizuje dostęp do sesji za pomocą _session_lock."""
    import asyncio
    from unittest.mock import AsyncMock

    client = LibrusApiClient("user", "pass", {}, hass=hass)
    client._client = MagicMock()
    client._token = "token"
    client._store = MagicMock()
    client._store.async_save = AsyncMock()

    call_order = []

    async def simulate_coordinator_holding_lock():
        async with client._session_lock:
            call_order.append("coordinator_start")
            await asyncio.sleep(0.05)
            call_order.append("coordinator_end")

    with patch("librus_apix.messages.message_content") as mock_mc:
        def fake_content(cl, href):
            call_order.append(f"fetch_{href}")
            return SimpleNamespace(content="Treść")
        mock_mc.side_effect = fake_content

        coord_task = hass.async_create_task(simulate_coordinator_holding_lock())
        client._start_background_message_fetcher(["/msg/1"])

        await coord_task
        if client._bg_fetch_task:
            await client._bg_fetch_task

        assert call_order == ["coordinator_start", "coordinator_end", "fetch_/msg/1"]
        assert client._message_cache["/msg/1"] == "Treść"






def test_63_atrybut_zawiera_href():
    """Odnośnik wiadomości jest w atrybucie (do akcji get_message), także w dopełnieniu."""
    coordinator = MagicMock()
    coordinator.data = {"wiadomosci": [
        {"author": "A", "title": "T", "date": "2026-11-20", "href": "4833629"},
        {"author": "B", "title": "U", "date": "2026-11-21", "href": 4833630},
    ]}
    attrs = LibrusWiadomosciSensor(coordinator, MagicMock(entry_id="e1", options={})).extra_state_attributes
    lista = attrs["wiadomosci"]
    assert lista[0]["href"] == "4833629"
    assert lista[1]["href"] == "4833630"
    assert all(m["href"] == "" for m in lista[2:])
    # Dotychczasowe klucze bez zmian
    assert {"nadawca", "temat", "data", "nieprzeczytana", "jest_nowa", "ma_zalacznik", "tresc"} <= set(lista[0])


@pytest.mark.asyncio
async def test_63_get_message_z_liczbowym_url(hass):
    """Szablon zwraca liczbę (HA zamienia "4833629" na int) - akcja i tak działa
    i dobiera właściwe konto po odnośniku."""
    from custom_components.librus_apix import async_setup
    from custom_components.librus_apix.const import DOMAIN

    def _klient(href):
        c = MagicMock(spec=LibrusApiClient)
        c._client = MagicMock()
        c._token = "token"
        c._message_cache = {}
        c.coordinator = MagicMock()
        c.coordinator.data = {"wiadomosci": [{"href": href}]}
        return c

    client_a, client_b = _klient("1111111"), _klient("4833629")
    await async_setup(hass, {})
    hass.data[DOMAIN]["entry_a"] = client_a
    hass.data[DOMAIN]["entry_b"] = client_b

    with patch("librus_apix.messages.message_content") as mock_mc:
        mock_mc.return_value = SimpleNamespace(content="Treść")
        response = await hass.services.async_call(
            DOMAIN, "get_message", {"url": 4833629}, blocking=True, return_response=True,
        )

    assert response == {"content": "Treść"}
    mock_mc.assert_called_once_with(client_b._client, "4833629")
