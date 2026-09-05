"""Platforma przycisków dla integracji Librus."""
import logging
from typing import Any, Dict

from homeassistant.components.button import ButtonEntity
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
    """Konfiguracja platformy przycisków."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = client.coordinator
    
    async_add_entities([
        LibrusRefreshButton(coordinator, config_entry)
    ])


class LibrusRefreshButton(CoordinatorEntity, ButtonEntity):
    """Przycisk do ręcznego odświeżenia danych z Librusa."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Odśwież dane"
        self._attr_icon = "mdi:refresh"
        self._attr_unique_id = f"{config_entry.entry_id}_refresh_button"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    async def async_press(self) -> None:
        """Wymuś odświeżenie danych u koordynatora."""
        _LOGGER.info("Wymuszenie ręcznego odświeżenia danych Librus...")
        await self.coordinator.async_request_refresh()
