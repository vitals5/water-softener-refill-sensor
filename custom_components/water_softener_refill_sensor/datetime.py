"""DateTime entity to manually correct the timestamp of the last regeneration."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EnthaertungEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([LastRegenerationDateTime(manager, entry)])


class LastRegenerationDateTime(EnthaertungEntity, DateTimeEntity):
    """Displays last regeneration and allows setting it manually without incrementing the counter."""

    _attr_icon = "mdi:calendar-edit"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, manager, entry: ConfigEntry) -> None:
        super().__init__(manager.coordinator, entry, "last_regeneration_input")
        self._manager = manager

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data["last_regeneration"]

    async def async_set_value(self, value: datetime) -> None:
        await self._manager.async_set_last_regeneration(value)
