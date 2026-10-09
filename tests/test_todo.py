import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock

from custom_components.librus_apix.todo import LibrusHomeworkTodoList

@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock()
    coordinator.data = {
        "zadania": [
            {
                "lekcja": "Matematyka",
                "przedmiot": "Zadanie domowe nr 1",
                "termin": "2026-09-14  pon.",
                "nauczyciel": "Jan Kowalski"
            },
            {
                "lekcja": "Język polski",
                "przedmiot": "Rozprawka",
                "termin": "2026-09-15  wto.",
                "nauczyciel": "Anna Nowak"
            },
            {
                "lekcja": "Fizyka",
                "przedmiot": "Brak terminu zadanie",
                "termin": "Brak daty",
                "nauczyciel": "Adam Wiśniewski"
            },
            {
                "lekcja": "", # Zdarza sie pusta lekcja
                "przedmiot": "Zadanie z pustej lekcji",
                "termin": "",
                "nauczyciel": ""
            }
        ]
    }
    return coordinator

def test_todo_items_extraction(mock_coordinator):
    """Test wyodrebniania kluczy oraz parsowania dat dla To-Do."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    
    todo_list = LibrusHomeworkTodoList(mock_coordinator, config_entry)
    items = todo_list.todo_items
    
    assert len(items) == 4
    
    # 1. Matematyka - normalna data z dniem tygodnia
    assert items[0].summary == "[Matematyka] Zadanie domowe nr 1"
    assert items[0].due == date(2026, 9, 14)
    assert items[0].description == "Jan Kowalski"
    
    # 2. Polski - kolejna normalna data
    assert items[1].summary == "[Język polski] Rozprawka"
    assert items[1].due == date(2026, 9, 15)
    assert items[1].description == "Anna Nowak"
    
    # 3. Fizyka - brak terminu
    assert items[2].summary == "[Fizyka] Brak terminu zadanie"
    assert items[2].due is None
    assert items[2].description == "Adam Wiśniewski"
    
    # 4. Puste dane
    assert items[3].summary == "[Zadanie z pustej lekcji] Zadanie z pustej lekcji"
    assert items[3].due is None
    assert items[3].description == ""
    
    # Weryfikacja ze identyfikatory (UID) sa unikalne
    uids = set([item.uid for item in items])
    assert len(uids) == 4


@pytest.mark.asyncio
async def test_study_todo_and_sensor_sync():
    """Weryfikacja wspoldzielenia stanu miedzy LibrusStudyTodoList i LibrusStudyCompletedSensor."""
    from datetime import timedelta
    from homeassistant.components.todo import TodoItem, TodoItemStatus
    from custom_components.librus_apix.todo import LibrusStudyTodoList
    from custom_components.librus_apix.binary_sensor import LibrusStudyCompletedSensor

    today = date.today()
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    far_str = (today + timedelta(days=10)).strftime("%Y-%m-%d")

    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.study_completed_uids = set()
    coordinator.study_store = MagicMock()
    coordinator.study_store.async_save = AsyncMock()
    coordinator.data = {
        "terminarz": [
            {
                "tytul": "Sprawdzian",
                "przedmiot": "Historia",
                "data": tomorrow_str,
                "szczegoly": {"Opis": "Rozdział 1-3"}
            },
            {
                "tytul": "Wycieczka",
                "przedmiot": "Geografia",
                "data": tomorrow_str,
                "szczegoly": {}
            },
            {
                "tytul": "Kartkówka",
                "przedmiot": "Biologia",
                "data": far_str,
                "szczegoly": {}
            }
        ]
    }

    config_entry = MagicMock()
    config_entry.entry_id = "test_entry"
    config_entry.options = {"days_before_exam_study": 2}

    todo = LibrusStudyTodoList(coordinator, config_entry)
    sensor = LibrusStudyCompletedSensor(coordinator, config_entry)

    # 1. Filtrowanie: tylko sprawdzian z jutra miesci sie w oknie 2 dni
    items = todo.todo_items
    assert len(items) == 1
    item = items[0]
    assert item.summary == "Nauka: Historia (Sprawdzian)"
    assert item.status == TodoItemStatus.NEEDS_ACTION

    # 2. Sensor binarny widzi nieodrobiona nauke (sprawdziany_do_nauki = 1, is_on = False)
    assert sensor.is_on is False
    assert sensor.extra_state_attributes["sprawdziany_do_nauki"] == 1
    assert sensor.extra_state_attributes["wszystkie_sprawdziany_w_oknie"] == 1

    # 3. Uczeń odhacza zadanie jako wykonane w Todo
    todo.hass = MagicMock()
    todo.async_write_ha_state = MagicMock()
    sensor.async_write_ha_state = MagicMock()
    updated_item = TodoItem(
        summary=item.summary,
        uid=item.uid,
        status=TodoItemStatus.COMPLETED
    )
    await todo.async_update_todo_item(updated_item)

    # Sprawdzenie ze UID trafil do wspoldzielonego zbioru i Store zostal zapisany
    assert item.uid in coordinator.study_completed_uids
    coordinator.study_store.async_save.assert_called_once_with({"completed": [item.uid]})

    # 4. Sensor binarny od razu odzwierciedla stan bez potrzeby czytania z dysku
    assert sensor.is_on is True
    assert sensor.extra_state_attributes["sprawdziany_do_nauki"] == 0

    # 5. Uczeń cofa wykonanie zadania
    uncompleted_item = TodoItem(
        summary=item.summary,
        uid=item.uid,
        status=TodoItemStatus.NEEDS_ACTION
    )
    await todo.async_update_todo_item(uncompleted_item)

    assert item.uid not in coordinator.study_completed_uids
    assert sensor.is_on is False
    assert sensor.extra_state_attributes["sprawdziany_do_nauki"] == 1


@pytest.mark.asyncio
async def test_coordinator_async_init_study_store():
    """Test inicjalizacji study_store w koordynatorze i wczytywania istniejacych zadan."""
    from custom_components.librus_apix.sensor import LibrusDataUpdateCoordinator
    from unittest.mock import patch

    hass = MagicMock()
    client = MagicMock()
    client.username = "test_user"

    coordinator = LibrusDataUpdateCoordinator(hass, client)
    assert coordinator.study_store is None
    assert coordinator.study_completed_uids == set()

    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={"completed": ["uid_abc", "uid_xyz"]})

    with patch("custom_components.librus_apix.sensor.Store", return_value=mock_store):
        await coordinator.async_init_study_store("entry_123")

    assert coordinator.study_store is mock_store
    assert coordinator.study_completed_uids == {"uid_abc", "uid_xyz"}
