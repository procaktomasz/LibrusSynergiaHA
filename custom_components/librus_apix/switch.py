import logging
from typing import Any, Dict

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Skonfiguruj platformę przełączników (switch)."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    
    if config_entry.options.get("ai_summary_enabled", False):
        async_add_entities([LibrusAISummarySwitch(config_entry)])


class LibrusAISummarySwitch(RestoreEntity, SwitchEntity):
    """Przełącznik włączający automatyczne cotygodniowe podsumowania AI."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Automatyczne Podsumowanie AI"
        self._attr_unique_id = f"{config_entry.entry_id}_ai_summary_switch"
        self._attr_icon = "mdi:robot-schedule"
        self._is_on = True

    @property
    def device_info(self) -> Dict[str, Any]:
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": "Librus",
            "manufacturer": "Librus",
            "model": "Synergia",
        }

    @property
    def is_on(self) -> bool:
        """Zwraca czy przełącznik jest włączony."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Włącz automatyczne podsumowania."""
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Wyłącz automatyczne podsumowania."""
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Przywróć stan po restarcie."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state:
            self._is_on = last_state.state == "on"
