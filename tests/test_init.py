"""Test the Librus APIX integration."""

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from unittest.mock import AsyncMock, patch, MagicMock

from custom_components.librus_apix.const import DOMAIN


@pytest.fixture
def mock_config_entry(hass):
    """Return a mock config entry added to hass."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Librus",
        data={"username": "test_user", "password": "test_password"},
        entry_id="test_entry_id",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_librus_client():
    """Return a mock Librus client."""
    client = MagicMock()
    client.async_authenticate = AsyncMock(return_value=True)
    client.async_get_grades = AsyncMock(return_value=[
        {
            'subject': 'Mathematyka',
            'grade': '5',
            'date': '2025-01-01',
            'category': 'Test',
            'teacher': 'Jan Kowalski',
            'type': 'numeric'
        }
    ])
    client.async_get_messages = AsyncMock(return_value=[])
    client.options = {}
    client.async_get_student_information = AsyncMock(return_value=None)
    for name in (
        "async_get_homework", "async_get_schedule", "async_get_timetable",
        "async_get_attendance", "async_get_announcements", "async_get_completed_lessons",
    ):
        setattr(client, name, AsyncMock(return_value=[]))
    client.async_get_attendance_stats = AsyncMock(return_value=None)
    client.async_get_notes = AsyncMock(return_value=[])
    return client


async def test_setup_entry(hass: HomeAssistant, mock_config_entry, mock_librus_client):
    """Test the setup entry."""
    with patch(
        "custom_components.librus_apix.LibrusApiClient",
        return_value=mock_librus_client
    ):
        result = await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert result is True
        assert mock_config_entry.state is ConfigEntryState.LOADED


async def test_unload_entry(hass: HomeAssistant, mock_config_entry, mock_librus_client):
    """Test unloading an entry."""
    with patch(
        "custom_components.librus_apix.LibrusApiClient",
        return_value=mock_librus_client
    ):
        # Setup first
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        
        # Then unload
        result = await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        assert result is True
        assert mock_config_entry.state is ConfigEntryState.NOT_LOADED