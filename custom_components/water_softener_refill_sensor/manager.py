"""Manager for water softener tracking: monitors power and energy, persists state, updates entities."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
    DEFAULT_PER_REGEN_KG,
    DEFAULT_POWER_THRESHOLD_W,
    DEFAULT_WARN_REMAINING,
    DOMAIN,
    SAVE_DELAY,
    STORAGE_VERSION,
    storage_key,
)
from .logic import EVAL_DELAY, Settings, SoftenerModel

_LOGGER = logging.getLogger(__name__)

UNIT_TO_KWH = {
    "kwh": 1.0,
    "kw⋅h": 1.0,
    "kw.h": 1.0,
    "wh": 0.001,
    "w⋅h": 0.001,
    "w.h": 0.001,
    "mwh": 1000.0,
}

UNIT_TO_W = {
    "w": 1.0,
    "watt": 1.0,
    "kw": 1000.0,
    "mw": 0.001,
}


def settings_from_entry(entry: ConfigEntry) -> Settings:
    """Build Settings dataclass from config entry data and options."""
    cfg = {**entry.data, **entry.options}
    start = cfg.get(CONF_WINDOW_START)
    end = cfg.get(CONF_WINDOW_END)
    start_hour = int(start) if start is not None and str(start).strip() != "" else None
    end_hour = int(end) if end is not None and str(end).strip() != "" else None

    return Settings(
        capacity_kg=float(cfg.get(CONF_CAPACITY_KG, DEFAULT_CAPACITY_KG)),
        per_regen_kg=float(cfg.get(CONF_PER_REGEN_KG, DEFAULT_PER_REGEN_KG)),
        power_threshold_w=float(cfg.get(CONF_POWER_THRESHOLD_W, DEFAULT_POWER_THRESHOLD_W)),
        energy_threshold_kwh=float(cfg.get(CONF_ENERGY_THRESHOLD_KWH, DEFAULT_ENERGY_THRESHOLD_KWH)),
        detection_mode=str(cfg.get(CONF_DETECTION_MODE, DEFAULT_DETECTION_MODE)),
        start_hour=start_hour,
        end_hour=end_hour,
        warn_remaining=int(cfg.get(CONF_WARN_REMAINING, DEFAULT_WARN_REMAINING)),
    )


class SoftenerManager:
    """Monitors smart plug power and energy, runs calculation model, and provides coordinator data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        cfg = {**entry.data, **entry.options}
        self.power_entity: str = cfg[CONF_POWER_ENTITY]
        self.energy_entity: str = cfg[CONF_ENERGY_ENTITY]
        self._initial_stock = cfg.get(CONF_INITIAL_STOCK_KG)
        self.settings = settings_from_entry(entry)
        self.model = SoftenerModel(self.settings, initial_stock_kg=self._initial_stock)
        self._store = Store(hass, STORAGE_VERSION, storage_key(entry.entry_id))
        self.coordinator: DataUpdateCoordinator = DataUpdateCoordinator(
            hass, _LOGGER, config_entry=entry, name=f"{DOMAIN}_{entry.entry_id}"
        )
        self._unsubs: list[Callable[[], None]] = []
        self._need_baseline = True  # After startup, set initial energy reference only
        self._power_unit_warned = False
        self._energy_unit_warned = False
        self.refill_input_kg: float = 0.0  # Refill amount input for button (not persisted)

    # ------------------------------------------------------------------ Startup / Shutdown
    async def async_start(self) -> None:
        """Start the manager, restore stored state, and register listeners."""
        stored = await self._store.async_load()
        if stored:
            self.model = SoftenerModel.from_dict(self.settings, stored)
        now = dt_util.now()

        # Catch up any window finalized during offline period
        events = self.model.evaluate_pending(now)
        if events:
            self._log_events(events)

        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.power_entity], self._handle_power_state_event)
        )
        self._unsubs.append(
            async_track_state_change_event(self.hass, [self.energy_entity], self._handle_energy_state_event)
        )

        eval_hour = 0 if self.settings.is_24h else (self.settings.end_hour or 0)
        self._unsubs.append(
            async_track_time_change(
                self.hass,
                self._handle_window_end,
                hour=eval_hour,
                minute=int(EVAL_DELAY.total_seconds() // 60),
                second=0,
            )
        )

        # Baseline energy and current power from existing states
        cur_energy = self.hass.states.get(self.energy_entity)
        if cur_energy is not None:
            self._process_energy_state(cur_energy, now)

        cur_power = self.hass.states.get(self.power_entity)
        if cur_power is not None:
            self._process_power_state(cur_power, now)

        self._publish()
        self._save_later()

    async def async_stop(self) -> None:
        """Stop tracking and persist current state."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._store.async_save(self.model.to_dict())

    # ------------------------------------------------------------------ Power processing
    def _to_watts(self, state: State) -> float | None:
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = str(state.attributes.get("unit_of_measurement") or "W").strip().lower()
        factor = UNIT_TO_W.get(unit)
        if factor is None:
            if not self._power_unit_warned:
                _LOGGER.warning(
                    "Unknown power unit %r for %s, assuming Watts (W)", unit, self.power_entity
                )
                self._power_unit_warned = True
            factor = 1.0
        return value * factor

    def _process_power_state(self, state: State, now: datetime) -> None:
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return
        watts = self._to_watts(state)
        if watts is None:
            return
        events = self.model.on_power(watts, now)
        if events:
            self._log_events(events)

    @callback
    def _handle_power_state_event(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self._process_power_state(new_state, dt_util.as_local(new_state.last_updated))
        self._publish()

    # ------------------------------------------------------------------ Energy processing
    def _to_kwh(self, state: State) -> float | None:
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        unit = str(state.attributes.get("unit_of_measurement") or "kWh").strip().lower()
        factor = UNIT_TO_KWH.get(unit)
        if factor is None:
            if not self._energy_unit_warned:
                _LOGGER.warning(
                    "Unknown energy unit %r for %s, assuming kilowatt-hours (kWh)", unit, self.energy_entity
                )
                self._energy_unit_warned = True
            factor = 1.0
        return value * factor

    def _process_energy_state(self, state: State, now: datetime) -> None:
        if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            self._need_baseline = True
            return
        kwh = self._to_kwh(state)
        if kwh is None:
            return
        events = self.model.on_energy(kwh, now, baseline_only=self._need_baseline)
        self._need_baseline = False
        if events:
            self._log_events(events)

    @callback
    def _handle_energy_state_event(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self._process_energy_state(new_state, dt_util.as_local(new_state.last_updated))
        self._publish()
        self._save_later()

    # ------------------------------------------------------------------ Window closing
    @callback
    def _handle_window_end(self, now: datetime) -> None:
        """Scheduled evaluation at end of time window or end of day."""
        events = self.model.evaluate_pending(dt_util.as_local(now), scheduled=True)
        if events:
            self._log_events(events)
        self._publish()
        self._save_later()

    def _log_events(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            if event["type"] == "regeneration":
                _LOGGER.info(
                    "Water softener regeneration detected (%s: %.3f kWh, max %.1f W), remaining stock: %s regenerations",
                    event["date"],
                    event.get("energy_kwh", 0.0),
                    event.get("max_power_w", 0.0),
                    self.model.remaining_regens,
                )
            elif event["type"] == "window_closed":
                _LOGGER.debug(
                    "Time window %s closed: %.3f kWh, max %.1f W",
                    event["date"],
                    event.get("energy_kwh", 0.0),
                    event.get("max_power_w", 0.0),
                )

    # ------------------------------------------------------------------ Manual actions & services
    async def async_refill(self, kg: float | None) -> None:
        """Confirm salt refilled with specific amount in kg."""
        if kg is None or not float(kg) > 0:
            raise ServiceValidationError("Please specify the refilled salt amount in kg (greater than 0).")
        added = self.model.refill(dt_util.now(), float(kg))
        if added < float(kg) - 1e-6:
            _LOGGER.warning(
                "Refilled %.2f kg, but only space for %.2f kg in tank; stock was clamped to capacity",
                float(kg),
                added,
            )
        self.refill_input_kg = 0.0
        self._after_manual_change()

    async def async_refill_full(self) -> None:
        """Set stock to capacity (tank full) without entering amount."""
        self.model.refill_full(dt_util.now())
        self.refill_input_kg = 0.0
        self._after_manual_change()

    def set_refill_input(self, kg: float) -> None:
        self.refill_input_kg = max(0.0, float(kg))
        self._publish()

    async def async_set_stock(self, kg: float) -> None:
        self.model.set_stock(kg)
        self._after_manual_change()

    async def async_add_regeneration(self, count: int = 1) -> None:
        self.model.add_manual_regeneration(dt_util.now(), count)
        self._after_manual_change()

    async def async_set_last_regeneration(self, at: datetime) -> None:
        """Set last regeneration timestamp manually."""
        if at.tzinfo is None:
            at = at.replace(tzinfo=dt_util.get_default_time_zone())
        try:
            self.model.set_last_regeneration(dt_util.as_local(at), dt_util.now())
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        self._after_manual_change()

    async def async_set_regens_since_refill(self, count: int) -> None:
        """Set known regenerations since full refill; recalculates salt stock."""
        try:
            self.model.set_regens_since_refill(count)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        self._after_manual_change()

    def _after_manual_change(self) -> None:
        self._publish()
        self._save_later()

    # ------------------------------------------------------------------ Coordinator data
    def snapshot(self) -> dict[str, Any]:
        m, s = self.model, self.model.state
        return {
            "total_regenerations": s.total_regens,
            "regenerations_since_refill": s.regens_since_refill,
            "salt_stock_kg": round(s.stock_kg, 2),
            "salt_percent": round(m.salt_percent, 1),
            "regenerations_left": m.remaining_regens,
            "last_regeneration": s.last_regen_at,
            "last_refill": s.last_refill_at,
            "window_energy_kwh": round(s.window_energy_kwh, 4) if s.window_date is not None else None,
            "window_max_power_w": round(s.window_max_power_w, 1) if s.window_date is not None else None,
            "current_power_w": round(s.current_power_w, 1),
            "is_regenerating": m.is_regenerating,
            "refill_needed": m.needs_refill,
            "next_regeneration_due": m.next_regen_due(dt_util.now().tzinfo),
            "regeneration_overdue": m.regen_overdue(dt_util.now()),
            "refill_input_kg": self.refill_input_kg,
            "history": [h.isoformat() for h in (s.history or [])],
            "capacity_kg": self.settings.capacity_kg,
            "per_regen_kg": self.settings.per_regen_kg,
            "warn_remaining": self.settings.warn_remaining,
            "power_threshold_w": self.settings.power_threshold_w,
            "energy_threshold_kwh": self.settings.energy_threshold_kwh,
            "detection_mode": self.settings.detection_mode,
            "window_start_hour": self.settings.start_hour,
            "window_end_hour": self.settings.end_hour,
            "is_24h": self.settings.is_24h,
        }

    def _publish(self) -> None:
        self.coordinator.async_set_updated_data(self.snapshot())

    def _save_later(self) -> None:
        self._store.async_delay_save(self.model.to_dict, SAVE_DELAY)
