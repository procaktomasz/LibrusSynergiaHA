"""Platforma zadań (todo) dla integracji Librus."""
import hashlib
import logging
from datetime import datetime, date
from typing import Any, Dict, List

from homeassistant.components.todo import TodoListEntity, TodoItem, TodoItemStatus
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy listy zadań."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = client.coordinator
    
    async_add_entities([
        LibrusHomeworkTodoList(coordinator, config_entry)
    ])


class LibrusHomeworkTodoList(CoordinatorEntity, TodoListEntity):
    """Lista zadań domowych z Librusa."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Zadania domowe (To-Do)"
        self._attr_unique_id = f"{config_entry.entry_id}_todo_zadania_domowe_to_do"
        self._attr_icon = "mdi:clipboard-list"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def todo_items(self) -> List[TodoItem] | None:
        """Zwraca listę zadań domowych."""
        data = self.coordinator.data or {}
        zadania = data.get("zadania", [])
        
        items = []
        for z in zadania:
            przedmiot = z.get("przedmiot", "Brak")
            tresc = z.get("tresc", "")
            data_str = z.get("data", "")
            
            # Generowanie bezpiecznego UID zadania (Librus nie zwraca unikalnego ID dla zadania)
            uid_str = f"{przedmiot}-{data_str}-{tresc}"
            uid = hashlib.md5(uid_str.encode('utf-8')).hexdigest()
            
            due_date = None
            if data_str and data_str != "Brak daty":
                try:
                    due_date = datetime.strptime(data_str, "%Y-%m-%d").date()
                except ValueError:
                    pass
            
            items.append(TodoItem(
                summary=f"[{przedmiot}]",
                uid=uid,
                status=TodoItemStatus.NEEDS_ACTION,
                due=due_date,
                description=tresc
            ))
            
        return items

    # Implementacja pustych metod asynchronicznych zapobiega zgłaszaniu błędów braku implementacji,
    # jednak Librus oficjalnie nie wspiera odznaczania zadań przez API
    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Dodawanie zadan nie jest wspierane."""
        pass

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Aktualizacja nie jest wspierana przez Librus."""
        pass

    async def async_delete_todo_items(self, uids: List[str]) -> None:
        """Usuwanie nie jest wspierane przez Librus."""
        pass
