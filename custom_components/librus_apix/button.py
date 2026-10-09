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
    
    buttons = [LibrusRefreshButton(coordinator, config_entry)]
    
    if config_entry.options.get("ai_summary_enabled", False):
        buttons.append(LibrusGenerateAISummaryButton(coordinator, config_entry))
        buttons.append(LibrusGenerateAIMessagesSummaryButton(coordinator, config_entry))
        
    async_add_entities(buttons)


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

class LibrusGenerateAISummaryButton(CoordinatorEntity, ButtonEntity):
    """Przycisk do ręcznego generowania podsumowania AI."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Generuj podsumowanie AI"
        self._attr_icon = "mdi:robot-outline"
        self._attr_unique_id = f"{config_entry.entry_id}_generate_ai_summary"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    async def async_press(self) -> None:
        """Uruchom wyliczanie podsumowania AI."""
        _LOGGER.info("Uruchamianie generowania podsumowania AI...")
        from .ai_summary import async_generate_summary
        
        agent_id = self._config_entry.options.get("ai_agent_id", "conversation.home_assistant")
        async def _run_summary():
            import asyncio
            await asyncio.sleep(1)
            await async_generate_summary(
                self.hass, 
                self._config_entry.entry_id, 
                self.coordinator.data,
                agent_id,
                self._config_entry.options
            )
        self.hass.async_create_task(_run_summary())

class LibrusGenerateAIMessagesSummaryButton(CoordinatorEntity, ButtonEntity):
    """Przycisk do ręcznego generowania podsumowania wiadomości AI."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Generuj podsumowanie wiadomości AI"
        self._attr_icon = "mdi:message-text-outline"
        self._attr_unique_id = f"{config_entry.entry_id}_generate_ai_messages_summary"

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    async def async_press(self) -> None:
        """Uruchom wyliczanie podsumowania wiadomości AI."""
        _LOGGER.info("Uruchamianie generowania podsumowania wiadomości AI...")
        from .ai_summary import async_generate_messages_summary
        
        agent_id = self._config_entry.options.get("ai_agent_id", "conversation.home_assistant")
        async def _run_messages():
            import asyncio
            await asyncio.sleep(1)
            await async_generate_messages_summary(
                self.hass, 
                self._config_entry.entry_id, 
                self.coordinator.data,
                agent_id,
                self._config_entry.options
            )
        self.hass.async_create_task(_run_messages())

