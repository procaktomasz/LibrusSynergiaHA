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
        LibrusHomeworkTodoList(coordinator, config_entry),
        LibrusStudyTodoList(coordinator, config_entry)
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
            przedmiot = z.get("lekcja", "") or z.get("przedmiot", "Brak")
            tresc = z.get("przedmiot", "")
            data_str = z.get("termin", "")
            
            # Generowanie bezpiecznego UID zadania (Librus nie zwraca unikalnego ID dla zadania)
            uid_str = f"{przedmiot}-{data_str}-{tresc}"
            uid = hashlib.md5(uid_str.encode('utf-8')).hexdigest()
            
            due_date = None
            if data_str and data_str != "Brak daty":
                try:
                    due_date = datetime.strptime(data_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    pass
            
            items.append(TodoItem(
                summary=f"[{przedmiot}] {tresc}".strip(),
                uid=uid,
                status=TodoItemStatus.NEEDS_ACTION,
                due=due_date,
                description=z.get("nauczyciel", "")
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


class LibrusStudyTodoList(CoordinatorEntity, TodoListEntity):
    """Lista przypomnień o nauce do sprawdzianów."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Przygotowanie do lekcji (To-Do)"
        self._attr_unique_id = f"{config_entry.entry_id}_todo_nauka_to_do"
        self._attr_icon = "mdi:book-open-variant"
        
        from homeassistant.helpers.storage import Store
        self._store = Store(coordinator.hass, 1, f"librus_apix_{config_entry.entry_id}_study")
        self._completed_uids = set()

    async def async_added_to_hass(self) -> None:
        """Kiedy encja zostaje dodana do HA."""
        await super().async_added_to_hass()
        data = await self._store.async_load()
        if data:
            self._completed_uids = set(data.get("completed", []))

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def todo_items(self) -> List[TodoItem] | None:
        """Zwraca listę przypomnień o nauce."""
        days_before = self._config_entry.options.get("days_before_exam_study", 2)
        if days_before <= 0:
            return []

        data = self.coordinator.data or {}
        terminarz = data.get("terminarz", [])
        
        items = []
        today = date.today()
        
        typy_testow = ["Sprawdzian", "Kartkówka", "Klasówka", "Praca klasowa"]
        
        for z in terminarz:
            if z.get("tytul") not in typy_testow:
                continue
                
            data_str = z.get("data", "")
            if not data_str:
                continue
                
            try:
                exam_date = datetime.strptime(data_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            
            days_until = (exam_date - today).days
            
            # Pokazujemy tylko sprawdziany w ciągu najblizszych `days_before` dni
            # i ukrywamy stare, zeby nie spamowaly.
            if 0 <= days_until <= days_before:
                przedmiot = z.get("przedmiot", "Brak")
                tytul = z.get("tytul", "")
                
                uid_str = f"{data_str}-{przedmiot}-{tytul}"
                uid = hashlib.md5(uid_str.encode('utf-8')).hexdigest()
                
                status = TodoItemStatus.COMPLETED if uid in self._completed_uids else TodoItemStatus.NEEDS_ACTION
                
                items.append(TodoItem(
                    summary=f"Nauka: {przedmiot} ({tytul})",
                    uid=uid,
                    status=status,
                    due=exam_date,
                    description=z.get("szczegoly", {}).get("Opis", "")
                ))
            
        return items

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Dodawanie ręczne nie jest wspierane."""
        pass

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Zapisuje lokalnie ze uczen odhaczyl ze sie uczył."""
        if item.status == TodoItemStatus.COMPLETED:
            self._completed_uids.add(item.uid)
        else:
            self._completed_uids.discard(item.uid)
            
        await self._store.async_save({"completed": list(self._completed_uids)})
        self.async_write_ha_state()

    async def async_delete_todo_items(self, uids: List[str]) -> None:
        """Usuwanie nie jest wspierane."""
        pass
