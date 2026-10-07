"""Water Softener Refill Sensor (Smart Plug Edition).

Monitors water softener regenerations and calculates salt stock using smart plug power and energy metrics.
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .const import (
    ATTR_CONFIG_ENTRY,
    ATTR_COUNT,
    ATTR_DATETIME,
    ATTR_KG,
    DOMAIN,
    PLATFORMS,
    SERVICE_ADD_REGENERATION,
    SERVICE_REFILL,
    SERVICE_SET_LAST_REGENERATION,
    SERVICE_SET_REGENS_SINCE_REFILL,
    SERVICE_SET_STOCK,
    STORAGE_VERSION,
    storage_key,
)
from .manager import SoftenerManager

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_ENTRY = {vol.Optional(ATTR_CONFIG_ENTRY): cv.string}
SCHEMA_REFILL = vol.Schema(
    {**_ENTRY, vol.Required(ATTR_KG): vol.All(vol.Coerce(float), vol.Range(min=0, min_included=False))}
)
SCHEMA_SET_STOCK = vol.Schema({**_ENTRY, vol.Required(ATTR_KG): vol.All(vol.Coerce(float), vol.Range(min=0))})
SCHEMA_ADD = vol.Schema({**_ENTRY, vol.Optional(ATTR_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=100))})
SCHEMA_SET_LAST = vol.Schema({**_ENTRY, vol.Required(ATTR_DATETIME): cv.datetime})
SCHEMA_SET_SINCE = vol.Schema({**_ENTRY, vol.Required(ATTR_COUNT): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000))})


def _manager_for(hass: HomeAssistant, call: ServiceCall) -> SoftenerManager:
    managers: dict[str, SoftenerManager] = hass.data.get(DOMAIN, {})
    entry_id = call.data.get(ATTR_CONFIG_ENTRY)
    if entry_id:
        if entry_id not in managers:
            raise ServiceValidationError(f"Unknown config entry: {entry_id}")
        return managers[entry_id]
    if len(managers) == 1:
        return next(iter(managers.values()))
    if not managers:
        raise ServiceValidationError("No water softener configured.")
    raise ServiceValidationError("Multiple water softeners configured: please specify config_entry.")


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register component-wide services."""
    hass.data.setdefault(DOMAIN, {})

    async def _refill(call: ServiceCall) -> None:
        await _manager_for(hass, call).async_refill(call.data[ATTR_KG])

    async def _set_stock(call: ServiceCall) -> None:
        await _manager_for(hass, call).async_set_stock(call.data[ATTR_KG])

    async def _add_regeneration(call: ServiceCall) -> None:
        await _manager_for(hass, call).async_add_regeneration(call.data[ATTR_COUNT])

    async def _set_last(call: ServiceCall) -> None:
        await _manager_for(hass, call).async_set_last_regeneration(call.data[ATTR_DATETIME])

    async def _set_since(call: ServiceCall) -> None:
        await _manager_for(hass, call).async_set_regens_since_refill(call.data[ATTR_COUNT])

    hass.services.async_register(DOMAIN, SERVICE_REFILL, _refill, schema=SCHEMA_REFILL)
    hass.services.async_register(DOMAIN, SERVICE_SET_STOCK, _set_stock, schema=SCHEMA_SET_STOCK)
    hass.services.async_register(DOMAIN, SERVICE_ADD_REGENERATION, _add_regeneration, schema=SCHEMA_ADD)
    hass.services.async_register(DOMAIN, SERVICE_SET_LAST_REGENERATION, _set_last, schema=SCHEMA_SET_LAST)
    hass.services.async_register(DOMAIN, SERVICE_SET_REGENS_SINCE_REFILL, _set_since, schema=SCHEMA_SET_SINCE)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Water Softener Refill Sensor from a config entry."""
    manager = SoftenerManager(hass, entry)
    await manager.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        manager: SoftenerManager = hass.data[DOMAIN].pop(entry.entry_id)
        await manager.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up storage on entry removal."""
    await Store(hass, STORAGE_VERSION, storage_key(entry.entry_id)).async_remove()


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
