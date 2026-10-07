"""Platforma sensorów binarnych dla integracji Librus."""
import hashlib
from datetime import datetime, date
from typing import Any, Dict

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .sensor import _device_info

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy binary_sensor dla Librus."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = client.coordinator
    
    async_add_entities([
        LibrusStudyReadyBinarySensor(coordinator, config_entry)
    ])


class LibrusStudyReadyBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Czujnik wskazujący, czy nauka do sprawdzianów na dziś i jutro została odrobiona."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Nauka odrobiona"
        self._attr_unique_id = f"{config_entry.entry_id}_nauka_odrobiona"
        self._attr_icon = "mdi:school"
        
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
    def is_on(self) -> bool:
        """Zwraca True, jeśli nie ma żadnych oczekujących sprawdzianów, z których trzeba się uczyć."""
        days_before = self._config_entry.options.get("days_before_exam_study", 2)
        if days_before <= 0:
            return True # Jeśli wyłączone przypomnienia, zawsze jesteśmy "Ready"

        data = self.coordinator.data or {}
        terminarz = data.get("terminarz", [])
        
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
            
            # Jeśli sprawdzian jest w ciągu najbliższych dni i nie jest zrobiony - sensor jest False
            if 0 <= days_until <= days_before:
                przedmiot = z.get("przedmiot", "Brak")
                tytul = z.get("tytul", "")
                
                uid_str = f"{data_str}-{przedmiot}-{tytul}"
                uid = hashlib.md5(uid_str.encode('utf-8')).hexdigest()
                
                if uid not in self._completed_uids:
                    return False
                    
        return True

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Dodatkowe atrybuty informacyjne."""
        data = self.coordinator.data or {}
        terminarz = data.get("terminarz", [])
        days_before = self._config_entry.options.get("days_before_exam_study", 2)
        
        niezrobione = []
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
            
            if 0 <= days_until <= days_before:
                przedmiot = z.get("przedmiot", "Brak")
                tytul = z.get("tytul", "")
                uid_str = f"{data_str}-{przedmiot}-{tytul}"
                uid = hashlib.md5(uid_str.encode('utf-8')).hexdigest()
                
                if uid not in self._completed_uids:
                    niezrobione.append(f"{przedmiot} ({tytul})")
                    
        return {
            "oczekujace_sprawdziany": niezrobione,
            "liczba_oczekujacych": len(niezrobione)
        }
