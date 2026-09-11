import pytest
from datetime import date
from unittest.mock import MagicMock

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
