import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator
from custom_components.librus_apix.__init__ import LibrusApiClient

@pytest.fixture
def mock_client():
    client = MagicMock(spec=LibrusApiClient)
    client.async_authenticate = AsyncMock(return_value=True)
    client.async_get_student_info = AsyncMock()
    client.async_get_grades = AsyncMock()
    client.async_get_messages = AsyncMock(return_value=[])
    client.async_get_homework = AsyncMock(return_value=[])
    client.async_get_schedule = AsyncMock(return_value=[])
    client.async_get_timetable = AsyncMock(return_value=[])
    client.async_get_attendance = AsyncMock(return_value=[])
    client.async_get_announcements = AsyncMock(return_value=[])
    return client

@pytest.fixture
def coordinator(hass, mock_client):
    # Dummy config entry
    config_entry = MagicMock()
    config_entry.entry_id = "test_123"
    
    # Utworz koordynator
    coord = LibrusDataUpdateCoordinator(hass, mock_client)
    return coord

@pytest.mark.asyncio
async def test_update_missing_grades(coordinator, mock_client):
    """Test czy pobranie None przy ocenach nie blokuje aktualizacji gdy cache jest puste."""
    
    # Mock zwrocenia None dla ocen (np. konto przedszkolaka)
    mock_client.async_get_grades.return_value = None
    
    # Mock student info
    student_info = MagicMock()
    student_info.name = "Jan Kowalski"
    student_info.class_name = "1A"
    mock_client.async_get_student_info.return_value = student_info
    
    # Upewnijmy sie ze koordynator ma puste dane
    coordinator.data = None
    
    # Zamiast wyrzucac wyjatek, powinno zwrocic puste tablice z fallbacku
    result = await coordinator._async_update_data()
    
    # Oceny powinny być pustą listą a nie rzucać UpdateFailed
    assert result["oceny"] == []
    assert result["student_info"].name == "Jan Kowalski"

@pytest.mark.asyncio
async def test_student_info_getattr_fix(coordinator, mock_client):
    """Test upewniajacy sie ze zabezpieczony dostep przez getattr nie rzuca wyjatkiem."""
    
    # Normalne oceny
    mock_client.async_get_grades.return_value = []
    
    # Symulujemy zwrocenie obiektu StudentInformation przez APIX
    class FakeStudentInformation:
        def __init__(self, name):
            self.name = name
            self.class_name = "2B"
    
    student_info = FakeStudentInformation("Piotr Nowak")
    mock_client.async_get_student_info.return_value = student_info
    
    result = await coordinator._async_update_data()
    
    assert result["student_info"].name == "Piotr Nowak"
    # To potwierdza ze wywolania getattr(student_info, 'name') wewnatrz integracji nie zglosza AttributeError
