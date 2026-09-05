"""Platforma kalendarza dla integracji Librus."""
import logging
from datetime import datetime, timedelta, date
from typing import Any, Dict, List

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
import zoneinfo

from .const import DOMAIN
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Konfiguracja platformy kalendarza."""
    client = hass.data[DOMAIN][config_entry.entry_id]
    coordinator = client.coordinator
    
    async_add_entities([
        LibrusTimetableCalendar(coordinator, config_entry),
        LibrusScheduleCalendar(coordinator, config_entry)
    ])


class LibrusTimetableCalendar(CoordinatorEntity, CalendarEntity):
    """Kalendarz planu lekcji."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Plan Lekcji"
        self._attr_unique_id = f"{config_entry.entry_id}_calendar_timetable"
        
        # Wymagane przez Home Assistant
        self._event: CalendarEvent | None = None

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def event(self) -> CalendarEvent | None:
        """Zwraca nastepne nadchodzace wydarzenie."""
        events = self._get_events()
        if not events:
            return None
            
        now = datetime.now(zoneinfo.ZoneInfo("Europe/Warsaw"))
        future_events = [e for e in events if e.start_datetime_local >= now]
        if future_events:
            return sorted(future_events, key=lambda e: e.start_datetime_local)[0]
        return None

    def _get_events(self) -> List[CalendarEvent]:
        """Pobiera i formatuje wydarzenia z koordynatora."""
        events = []
        data = self.coordinator.data or {}
        plan = data.get("plan_lekcji", [])
        
        tz = zoneinfo.ZoneInfo("Europe/Warsaw")
        
        for day in plan:
            for lekcja in day:
                try:
                    # Format: YYYY-MM-DD
                    lekcja_data = lekcja.get("data")
                    if not lekcja_data:
                        continue
                        
                    # Format: HH:MM
                    godzina_od = lekcja.get("godzina_od")
                    godzina_do = lekcja.get("godzina_do")
                    if not godzina_od or not godzina_do:
                        continue
                        
                    dt_od = datetime.strptime(f"{lekcja_data} {godzina_od}", "%Y-%m-%d %H:%M")
                    dt_do = datetime.strptime(f"{lekcja_data} {godzina_do}", "%Y-%m-%d %H:%M")
                    
                    dt_od = dt_od.replace(tzinfo=tz)
                    dt_do = dt_do.replace(tzinfo=tz)
                    
                    summary = lekcja.get("przedmiot", "Lekcja")
                    sala = lekcja.get("nauczyciel_i_sala", "")
                    description = f"Nauczyciel i sala: {sala}" if sala else ""
                    
                    events.append(
                        CalendarEvent(
                            start=dt_od,
                            end=dt_do,
                            summary=summary,
                            description=description,
                            location=sala
                        )
                    )
                except ValueError as ex:
                    _LOGGER.error("Błąd parsowania daty w planie lekcji: %s", ex)
                    
        return events

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> List[CalendarEvent]:
        """Zwraca wydarzenia dla danego zakresu dat."""
        events = self._get_events()
        return [
            e for e in events 
            if e.start_datetime_local >= start_date and e.start_datetime_local < end_date
        ]


class LibrusScheduleCalendar(CoordinatorEntity, CalendarEntity):
    """Kalendarz sprawdzianow i kartkowek (Terminarz)."""

    def __init__(self, coordinator, config_entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._attr_has_entity_name = False
        self._attr_name = "Terminarz"
        self._attr_unique_id = f"{config_entry.entry_id}_calendar_schedule"
        
        self._event: CalendarEvent | None = None

    @property
    def device_info(self) -> Dict[str, Any]:
        return _device_info(self.coordinator, self._config_entry)

    @property
    def event(self) -> CalendarEvent | None:
        events = self._get_events()
        if not events:
            return None
            
        today = date.today()
        future_events = [e for e in events if e.start >= today]
        if future_events:
            return sorted(future_events, key=lambda e: e.start)[0]
        return None

    def _get_events(self) -> List[CalendarEvent]:
        events = []
        data = self.coordinator.data or {}
        terminarz = data.get("terminarz", [])
        
        for ev in terminarz:
            try:
                ev_data = ev.get("data")
                if not ev_data:
                    continue
                    
                dt_start = datetime.strptime(ev_data, "%Y-%m-%d").date()
                dt_end = dt_start + timedelta(days=1)
                
                przedmiot = ev.get("przedmiot", "")
                tytul = ev.get("tytul", "")
                szczegoly = ev.get("szczegoly", "")
                
                summary = f"[{przedmiot}] {tytul}" if przedmiot else tytul
                description = f"{szczegoly}"
                
                events.append(
                    CalendarEvent(
                        start=dt_start,
                        end=dt_end,
                        summary=summary,
                        description=description
                    )
                )
            except ValueError as ex:
                _LOGGER.error("Błąd parsowania daty w terminarzu: %s", ex)
                
        return events

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> List[CalendarEvent]:
        events = self._get_events()
        start_d = start_date.date()
        end_d = end_date.date()
        return [
            e for e in events 
            if e.start >= start_d and e.start < end_d
        ]
