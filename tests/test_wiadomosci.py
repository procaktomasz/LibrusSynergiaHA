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

