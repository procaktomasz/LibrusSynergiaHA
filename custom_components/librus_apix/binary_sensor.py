"""Platforma czujników binarnych (gamifikacja) dla integracji Librus."""
import hashlib
import logging
from datetime import datetime, date
from typing import Any, Dict

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy czujników binarnych."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = client.coordinator
    
    async_add_entities([
        LibrusStudyCompletedSensor(coordinator, config_entry)
    ])


class LibrusStudyCompletedSensor(CoordinatorEntity, BinarySensorEntity):
    """Czujnik sprawdzający, czy uczeń odrobił lekcje / naukę na najbliższe sprawdziany."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Obowiązki szkolne (Nauka)"
        self._attr_unique_id = f"{config_entry.entry_id}_gamifikacja_nauka"
        self._attr_device_class = None
        self._attr_icon = "mdi:gamepad-circle"
        
    @property
    def _completed_uids(self) -> set:
        return getattr(self.coordinator, "study_completed_uids", set())

    async def async_added_to_hass(self) -> None:
        """Kiedy encja zostaje dodana do HA."""
        await super().async_added_to_hass()
        if hasattr(self.coordinator, "async_init_study_store"):
            await self.coordinator.async_init_study_store(self._config_entry.entry_id)
            
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"librus_apix_{self._config_entry.entry_id}_study_updated",
                self._async_study_updated
            )
        )
            
    async def _async_study_updated(self) -> None:
        """Wywoływane, gdy uczeń zaznaczy/odznaczy zadanie w panelu."""
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Odświeża stan encji."""
        pass

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def is_on(self) -> bool | None:
        """
        Zwraca True, jeśli uczeń nie ma nadchodzących sprawdzianów
        lub wszystkie nadchodzące sprawdziany ma odznaczone jako 'nauka odrobiona'.
        """
        days_before = self._config_entry.options.get("days_before_exam_study", 2)
        if days_before <= 0:
            return True  # Jeśli funkcja wyłączona, obowiązki są 'odrobione'
            
        data = self.coordinator.data or {}
        terminarz = data.get("terminarz", [])
        
        today = date.today()
        typy_testow = ["Sprawdzian", "Kartkówka", "Klasówka", "Praca klasowa"]
        
        pending_count = 0
        total_count = 0
        
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
            
            # Bierzemy pod uwagę tylko te same sprawdziany, co lista To-Do
            if 0 <= days_until <= days_before:
                przedmiot = z.get("przedmiot", "Brak")
                tytul = z.get("tytul", "")
                uid_str = f"{data_str}-{przedmiot}-{tytul}"
                uid = hashlib.md5(uid_str.encode('utf-8')).hexdigest()
                
                total_count += 1
                if uid not in self._completed_uids:
                    pending_count += 1
                    
        # Jeśli pending_count == 0, to uczeń odrobił wszystkie lekcje (stan ON)
        self._attr_extra_state_attributes = {
            "sprawdziany_do_nauki": pending_count,
            "wszystkie_sprawdziany_w_oknie": total_count,
        }
        
        return pending_count == 0
