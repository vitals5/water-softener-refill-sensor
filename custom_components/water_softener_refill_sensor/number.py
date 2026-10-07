"""Number entities for refill amount input and manual counter adjustments."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EnthaertungEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RefillAmountNumber(manager, entry), RegenerationsSinceRefillNumber(manager, entry)])


class RefillAmountNumber(EnthaertungEntity, NumberEntity):
    """Refilled salt amount in kg. Reset to 0 when confirmed via button or service."""

    _attr_icon = "mdi:scale-bathroom"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS

    def __init__(self, manager, entry: ConfigEntry) -> None:
        super().__init__(manager.coordinator, entry, "refill_amount")
        self._manager = manager

    @property
    def native_max_value(self) -> float:
        return float(self._manager.settings.capacity_kg)

    @property
    def native_value(self) -> float:
        return float(self.coordinator.data["refill_input_kg"])

    async def async_set_native_value(self, value: float) -> None:
        self._manager.set_refill_input(value)


class RegenerationsSinceRefillNumber(EnthaertungEntity, NumberEntity):
    """Correct known regenerations since last full refill; recalculates calculated stock."""

    _attr_icon = "mdi:counter"
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = 0
    _attr_native_max_value = 1000
    _attr_native_step = 1

    def __init__(self, manager, entry: ConfigEntry) -> None:
        super().__init__(manager.coordinator, entry, "regenerations_since_refill_input")
        self._manager = manager

    @property
    def native_value(self) -> float:
        return float(self.coordinator.data["regenerations_since_refill"])

    async def async_set_native_value(self, value: float) -> None:
        await self._manager.async_set_regens_since_refill(int(round(value)))
