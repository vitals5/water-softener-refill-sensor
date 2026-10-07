"""Binary sensors: low salt warning, overdue regeneration, and currently regenerating."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import EnthaertungEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RefillNeededBinarySensor(manager.coordinator, entry),
            RegenerationOverdueBinarySensor(manager.coordinator, entry),
            RegeneratingBinarySensor(manager.coordinator, entry),
        ]
    )


class RefillNeededBinarySensor(EnthaertungEntity, BinarySensorEntity):
    """Active when calculated salt stock drops to or below warning threshold."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "refill_needed")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["refill_needed"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {"regenerations_left": data["regenerations_left"], "salt_stock_kg": data["salt_stock_kg"]}


class RegenerationOverdueBinarySensor(EnthaertungEntity, BinarySensorEntity):
    """Active when no regeneration was detected for more than 7 days (hygiene regeneration)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "regeneration_overdue")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["regeneration_overdue"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"next_regeneration_due": self.coordinator.data["next_regeneration_due"]}


class RegeneratingBinarySensor(EnthaertungEntity, BinarySensorEntity):
    """Active while the water softener is currently regenerating (power >= threshold)."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "regenerating")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data["is_regenerating"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "current_power_w": data["current_power_w"],
            "threshold_w": data["power_threshold_w"],
        }
