"""Configuration and options flow for the Water Softener Refill Sensor."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_CAPACITY_KG,
    CONF_DETECTION_MODE,
    CONF_ENERGY_ENTITY,
    CONF_ENERGY_THRESHOLD_KWH,
    CONF_INITIAL_STOCK_KG,
    CONF_PER_REGEN_KG,
    CONF_POWER_ENTITY,
    CONF_POWER_THRESHOLD_W,
    CONF_WARN_REMAINING,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    DEFAULT_CAPACITY_KG,
    DEFAULT_DETECTION_MODE,
    DEFAULT_ENERGY_THRESHOLD_KWH,
    DEFAULT_NAME,
    DEFAULT_PER_REGEN_KG,
    DEFAULT_POWER_THRESHOLD_W,
    DEFAULT_WARN_REMAINING,
    DETECTION_MODES,
    DOMAIN,
)


def _number(minimum: float, maximum: float, step: float, unit: str | None = None) -> NumberSelector:
    options: dict[str, Any] = {"min": minimum, "max": maximum, "step": step, "mode": NumberSelectorMode.BOX}
    if unit is not None:
        options["unit_of_measurement"] = unit
    return NumberSelector(NumberSelectorConfig(**options))


def _schema(first_setup: bool, defaults: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if first_setup:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME))] = TextSelector()

    fields[vol.Required(CONF_POWER_ENTITY, default=defaults.get(CONF_POWER_ENTITY, vol.UNDEFINED))] = EntitySelector(
        EntitySelectorConfig(domain="sensor")
    )
    fields[vol.Required(CONF_ENERGY_ENTITY, default=defaults.get(CONF_ENERGY_ENTITY, vol.UNDEFINED))] = EntitySelector(
        EntitySelectorConfig(domain="sensor")
    )
    fields[
        vol.Required(
            CONF_POWER_THRESHOLD_W,
            default=defaults.get(CONF_POWER_THRESHOLD_W, DEFAULT_POWER_THRESHOLD_W),
        )
    ] = _number(0.1, 1000, 0.5, "W")

    fields[
        vol.Required(
            CONF_ENERGY_THRESHOLD_KWH,
            default=defaults.get(CONF_ENERGY_THRESHOLD_KWH, DEFAULT_ENERGY_THRESHOLD_KWH),
        )
    ] = _number(0.001, 10, 0.001, "kWh")

    fields[
        vol.Required(
            CONF_DETECTION_MODE,
            default=defaults.get(CONF_DETECTION_MODE, DEFAULT_DETECTION_MODE),
        )
    ] = SelectSelector(
        SelectSelectorConfig(
            options=DETECTION_MODES,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="detection_mode",
        )
    )

    fields[vol.Required(CONF_CAPACITY_KG, default=defaults.get(CONF_CAPACITY_KG, DEFAULT_CAPACITY_KG))] = _number(
        1, 1000, 0.5, "kg"
    )
    fields[vol.Required(CONF_PER_REGEN_KG, default=defaults.get(CONF_PER_REGEN_KG, DEFAULT_PER_REGEN_KG))] = _number(
        0.01, 100, 0.01, "kg"
    )

    if first_setup:
        init_stock = defaults.get(CONF_INITIAL_STOCK_KG)
        if init_stock is not None:
            fields[vol.Optional(CONF_INITIAL_STOCK_KG, default=init_stock)] = _number(0, 1000, 0.5, "kg")
        else:
            fields[vol.Optional(CONF_INITIAL_STOCK_KG)] = _number(0, 1000, 0.5, "kg")

    start_val = defaults.get(CONF_WINDOW_START)
    if start_val is not None:
        fields[vol.Optional(CONF_WINDOW_START, default=start_val)] = _number(0, 23, 1, "h")
    else:
        fields[vol.Optional(CONF_WINDOW_START)] = _number(0, 23, 1, "h")

    end_val = defaults.get(CONF_WINDOW_END)
    if end_val is not None:
        fields[vol.Optional(CONF_WINDOW_END, default=end_val)] = _number(1, 24, 1, "h")
    else:
        fields[vol.Optional(CONF_WINDOW_END)] = _number(1, 24, 1, "h")

    fields[vol.Required(CONF_WARN_REMAINING, default=defaults.get(CONF_WARN_REMAINING, DEFAULT_WARN_REMAINING))] = (
        _number(0, 100, 1)
    )

    return vol.Schema(fields)


def _normalize(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    if CONF_WARN_REMAINING in data:
        data[CONF_WARN_REMAINING] = int(round(float(data[CONF_WARN_REMAINING])))

    for key in (CONF_WINDOW_START, CONF_WINDOW_END):
        val = data.get(key)
        if val is not None and str(val).strip() != "":
            data[key] = int(round(float(val)))
        else:
            data[key] = None

    for key in (CONF_POWER_THRESHOLD_W, CONF_ENERGY_THRESHOLD_KWH, CONF_CAPACITY_KG, CONF_PER_REGEN_KG, CONF_INITIAL_STOCK_KG):
        if key in data and data[key] is not None and str(data[key]).strip() != "":
            data[key] = float(data[key])
        elif key == CONF_INITIAL_STOCK_KG:
            data[key] = None

    if CONF_DETECTION_MODE in data:
        data[CONF_DETECTION_MODE] = str(data[CONF_DETECTION_MODE])
    return data


def _validate(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    start = data.get(CONF_WINDOW_START)
    end = data.get(CONF_WINDOW_END)
    if (start is not None and end is None) or (start is None and end is not None):
        errors["base"] = "window_incomplete"
    elif start is not None and end is not None and start >= end:
        errors["base"] = "window_invalid"
    elif data[CONF_PER_REGEN_KG] > data[CONF_CAPACITY_KG]:
        errors["base"] = "per_regen_too_large"
    elif data.get(CONF_INITIAL_STOCK_KG) is not None and data[CONF_INITIAL_STOCK_KG] > data[CONF_CAPACITY_KG]:
        errors["base"] = "stock_too_large"
    elif data[CONF_POWER_THRESHOLD_W] <= 0:
        errors["base"] = "power_threshold_invalid"
    elif data[CONF_ENERGY_THRESHOLD_KWH] <= 0:
        errors["base"] = "energy_threshold_invalid"
    return errors


class EnthaertungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle water softener config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = {}
        if user_input is not None:
            data = _normalize(user_input)
            errors = _validate(data)
            if not errors:
                return self.async_create_entry(title=data[CONF_NAME], data=data)
            defaults = data
        return self.async_show_form(step_id="user", data_schema=_schema(True, defaults), errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return EnthaertungOptionsFlow()


class EnthaertungOptionsFlow(OptionsFlow):
    """Handle options flow to modify settings after setup."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            data = _normalize(user_input)
            errors = _validate(data)
            if not errors:
                return self.async_create_entry(title="", data=data)
            current = {**current, **data}
        return self.async_show_form(step_id="init", data_schema=_schema(False, current), errors=errors)
