"""Pure logic for water softener regeneration detection and salt stock tracking via smart plug.

This module has no Home Assistant dependencies to allow isolated testing.
All timestamps are timezone-aware datetime objects.

Working principle:
-----------------
* A smart plug with power measurement (instantaneous [W]) and energy measurement (cumulative [kWh])
  is attached to the water softener.
* Softeners typically regenerate during a scheduled night time window (default: 02:00 to 03:00).
* During regeneration, the motor/valve mechanisms draw active power (e.g. 5–30+ W) and accumulate
  electrical energy (e.g. 0.015–0.05+ kWh).
* Active power [W] also provides a real-time binary sensor indicating whether a regeneration is currently in progress.
* One minute after the time window closes, the window is finalized: if the energy consumption or power drawn
  exceeds the configured threshold(s), one regeneration cycle is counted.
* Each regeneration reduces the calculated salt stock by a configurable amount.
* Refilling salt updates the stock and resets warning states.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from .const import (
    DEFAULT_CAPACITY_KG,
    DEFAULT_DETECTION_MODE,
    DEFAULT_ENERGY_THRESHOLD_KWH,
    DEFAULT_PER_REGEN_KG,
    DEFAULT_POWER_THRESHOLD_W,
    DEFAULT_WARN_REMAINING,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    MODE_BOTH,
    MODE_ENERGY_ONLY,
    MODE_ENERGY_OR_POWER,
    MODE_POWER_ONLY,
)

EVAL_DELAY = timedelta(minutes=1)
HYGIENE_DAYS = 7
HISTORY_LENGTH = 10


@dataclass
class Settings:
    """Water softener configuration settings."""

    capacity_kg: float = DEFAULT_CAPACITY_KG
    per_regen_kg: float = DEFAULT_PER_REGEN_KG
    power_threshold_w: float = DEFAULT_POWER_THRESHOLD_W
    energy_threshold_kwh: float = DEFAULT_ENERGY_THRESHOLD_KWH
    detection_mode: str = DEFAULT_DETECTION_MODE
    start_hour: int = DEFAULT_WINDOW_START
    end_hour: int = DEFAULT_WINDOW_END
    warn_remaining: int = DEFAULT_WARN_REMAINING


@dataclass
class State:
    """Mutable persistent state."""

    stock_kg: float
    total_regens: int = 0
    regens_since_refill: int = 0
    last_energy_kwh: float | None = None
    window_date: date | None = None
    window_energy_kwh: float = 0.0
    window_max_power_w: float = 0.0
    window_crossed_at: datetime | None = None
    evaluated_date: date | None = None
    last_regen_at: datetime | None = None
    last_refill_at: datetime | None = None
    history: list[datetime] | None = None
    current_power_w: float = 0.0

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class SoftenerModel:
    """Core calculation model: tracks regenerations and calculates salt stock."""

    def __init__(
        self,
        settings: Settings,
        state: State | None = None,
        initial_stock_kg: float | None = None,
    ) -> None:
        self.settings = settings
        if state is None:
            stock = settings.capacity_kg if initial_stock_kg is None else initial_stock_kg
            state = State(stock_kg=self._clamp(stock))
        self.state = state
        self.state.stock_kg = self._clamp(self.state.stock_kg)

    # ------------------------------------------------------------------ Helper functions
    def _clamp(self, kg: float) -> float:
        return max(0.0, min(float(kg), float(self.settings.capacity_kg)))

    def window_start(self, day: date, tz: Any) -> datetime:
        return datetime.combine(day, time(self.settings.start_hour, 0), tzinfo=tz)

    def window_end(self, day: date, tz: Any) -> datetime:
        """End of detection window + evaluation delay."""
        return datetime.combine(day, time(self.settings.end_hour, 0), tzinfo=tz) + EVAL_DELAY

    def in_window(self, now: datetime) -> bool:
        day = now.date()
        return self.window_start(day, now.tzinfo) <= now < self.window_end(day, now.tzinfo)

    # ------------------------------------------------------------------ Metrics
    @property
    def remaining_regens(self) -> int:
        """Calculated remaining regenerations (rounded down)."""
        if self.settings.per_regen_kg <= 0:
            return 0
        return int(math.floor(self.state.stock_kg / self.settings.per_regen_kg + 1e-9))

    @property
    def salt_percent(self) -> float:
        if self.settings.capacity_kg <= 0:
            return 0.0
        return 100.0 * self.state.stock_kg / self.settings.capacity_kg

    @property
    def needs_refill(self) -> bool:
        return self.remaining_regens <= self.settings.warn_remaining

    @property
    def is_regenerating(self) -> bool:
        """True if the appliance is currently drawing power at or above threshold."""
        return self.state.current_power_w >= self.settings.power_threshold_w

    # ------------------------------------------------------------------ Hygiene rule (7 days)
    def next_regen_due(self, tz: Any) -> datetime | None:
        """Latest due timestamp of next regeneration (start of window 7 days after last)."""
        last = self.state.last_regen_at
        if last is None:
            return None
        due_day = last.astimezone(tz).date() + timedelta(days=HYGIENE_DAYS)
        return self.window_start(due_day, tz)

    def regen_overdue(self, now: datetime) -> bool:
        """True if the time window on the due day closed and no regeneration was detected."""
        due = self.next_regen_due(now.tzinfo)
        if due is None:
            return False
        return now >= self.window_end(due.date(), now.tzinfo)

    # ------------------------------------------------------------------ Threshold evaluation
    def check_threshold_reached(self, energy_kwh: float, max_power_w: float) -> bool:
        """Determine whether energy/power meet the configured detection mode."""
        mode = self.settings.detection_mode
        e_ok = energy_kwh >= self.settings.energy_threshold_kwh
        p_ok = max_power_w >= self.settings.power_threshold_w

        if mode == MODE_ENERGY_ONLY:
            return e_ok
        if mode == MODE_POWER_ONLY:
            return p_ok
        if mode == MODE_BOTH:
            return e_ok and p_ok
        # Default: MODE_ENERGY_OR_POWER
        return e_ok or p_ok

    # ------------------------------------------------------------------ Power & Energy input
    def on_power(self, power_w: float, now: datetime) -> list[dict[str, Any]]:
        """Process new instantaneous power reading in Watts [W]."""
        events = self.evaluate_pending(now)
        st = self.state
        st.current_power_w = max(0.0, float(power_w))

        if self.in_window(now):
            day = now.date()
            if st.window_date != day:
                st.window_date = day
                st.window_energy_kwh = 0.0
                st.window_max_power_w = st.current_power_w
                st.window_crossed_at = None
            else:
                st.window_max_power_w = max(st.window_max_power_w, st.current_power_w)

            if st.window_crossed_at is None and self.check_threshold_reached(
                st.window_energy_kwh, st.window_max_power_w
            ):
                st.window_crossed_at = now

        return events

    def on_energy(self, energy_kwh: float, now: datetime, baseline_only: bool = False) -> list[dict[str, Any]]:
        """Process cumulative energy reading in kilowatt-hours [kWh].

        baseline_only=True initializes the baseline reference without accumulating delta,
        preventing gaps after HA restarts or temporary sensor unavailability from counting as usage.
        """
        events = self.evaluate_pending(now)
        st = self.state
        prev = st.last_energy_kwh
        st.last_energy_kwh = float(energy_kwh)

        if baseline_only or prev is None:
            return events

        delta = float(energy_kwh) - prev
        if delta <= 0:  # unchanged or reset/meter swap
            return events

        if self.in_window(now):
            day = now.date()
            if st.window_date != day:
                st.window_date = day
                st.window_energy_kwh = 0.0
                st.window_max_power_w = st.current_power_w
                st.window_crossed_at = None
            st.window_energy_kwh += delta

            if st.window_crossed_at is None and self.check_threshold_reached(
                st.window_energy_kwh, st.window_max_power_w
            ):
                st.window_crossed_at = now

        return events

    # ------------------------------------------------------------------ Window finalization
    def evaluate_pending(self, now: datetime, scheduled: bool = False) -> list[dict[str, Any]]:
        """Finalize an ended time window that has not yet been evaluated."""
        st = self.state
        today = now.date()
        wd = st.window_date

        if wd is not None and st.evaluated_date != wd:
            if now >= self.window_end(wd, now.tzinfo):
                return self._finalize(wd, now.tzinfo)
            return []

        if scheduled and st.evaluated_date != today and now >= self.window_end(today, now.tzinfo):
            st.window_date = today
            st.window_energy_kwh = 0.0
            st.window_max_power_w = st.current_power_w
            st.window_crossed_at = None
            st.evaluated_date = today
            return [{"type": "window_closed", "date": today, "energy_kwh": 0.0, "max_power_w": st.current_power_w}]

        return []

    def _finalize(self, day: date, tz: Any) -> list[dict[str, Any]]:
        st = self.state
        st.evaluated_date = day
        energy = round(st.window_energy_kwh, 4)
        max_power = round(st.window_max_power_w, 2)

        events: list[dict[str, Any]] = [
            {"type": "window_closed", "date": day, "energy_kwh": energy, "max_power_w": max_power}
        ]

        if self.check_threshold_reached(energy, max_power):
            at = st.window_crossed_at or self.window_end(day, tz)
            self._register(at)
            events.append(
                {
                    "type": "regeneration",
                    "date": day,
                    "at": at,
                    "energy_kwh": energy,
                    "max_power_w": max_power,
                    "manual": False,
                }
            )

        return events

    def _register(self, at: datetime) -> None:
        st = self.state
        st.total_regens += 1
        st.regens_since_refill += 1
        st.stock_kg = self._clamp(round(st.stock_kg - self.settings.per_regen_kg, 4))
        st.last_regen_at = at
        st.history = ([at] + (st.history or []))[:HISTORY_LENGTH]

    # ------------------------------------------------------------------ Manual actions
    def add_manual_regeneration(self, at: datetime, count: int = 1) -> None:
        """Manually register one or more missed regenerations."""
        for _ in range(max(0, int(count))):
            self._register(at)

    def refill(self, now: datetime, kg: float) -> float:
        """Confirm salt refill with given kg (must be > 0).

        Added to current stock up to tank capacity.
        If tank is full after refill, regens_since_refill resets to 0.
        Returns the amount effectively added.
        """
        if kg is None or not float(kg) > 0:
            raise ValueError("Refill amount must be greater than 0 kg.")
        st = self.state
        before = st.stock_kg
        st.stock_kg = self._clamp(round(before + float(kg), 4))
        if st.stock_kg >= float(self.settings.capacity_kg) - 1e-9:
            st.regens_since_refill = 0
        st.last_refill_at = now
        return round(st.stock_kg - before, 4)

    def refill_full(self, now: datetime) -> float:
        """Mark tank as full (resets stock to capacity and counter to 0)."""
        st = self.state
        before = st.stock_kg
        st.stock_kg = self._clamp(self.settings.capacity_kg)
        st.regens_since_refill = 0
        st.last_refill_at = now
        return round(st.stock_kg - before, 4)

    def set_stock(self, kg: float) -> None:
        """Directly set the salt stock in kg."""
        self.state.stock_kg = self._clamp(kg)

    def set_last_regeneration(self, at: datetime, now: datetime) -> None:
        """Manually correct timestamp of last regeneration (cannot be in the future)."""
        if at > now:
            raise ValueError("Last regeneration timestamp cannot be in the future.")
        self.state.last_regen_at = at

    def set_regens_since_refill(self, count: int) -> None:
        """Set known regenerations since last full refill; recalculates stock accordingly."""
        count = int(count)
        if count < 0:
            raise ValueError("Regenerations count cannot be negative.")
        st = self.state
        st.regens_since_refill = count
        st.stock_kg = self._clamp(round(self.settings.capacity_kg - count * self.settings.per_regen_kg, 4))
        st.total_regens = max(st.total_regens, count)

    # ------------------------------------------------------------------ Persistence serialization
    def to_dict(self) -> dict[str, Any]:
        s = self.state
        return {
            "stock_kg": s.stock_kg,
            "total_regens": s.total_regens,
            "regens_since_refill": s.regens_since_refill,
            "last_energy_kwh": s.last_energy_kwh,
            "window_date": s.window_date.isoformat() if s.window_date else None,
            "window_energy_kwh": s.window_energy_kwh,
            "window_max_power_w": s.window_max_power_w,
            "window_crossed_at": s.window_crossed_at.isoformat() if s.window_crossed_at else None,
            "evaluated_date": s.evaluated_date.isoformat() if s.evaluated_date else None,
            "last_regen_at": s.last_regen_at.isoformat() if s.last_regen_at else None,
            "last_refill_at": s.last_refill_at.isoformat() if s.last_refill_at else None,
            "history": [h.isoformat() for h in (s.history or [])],
        }

    @classmethod
    def from_dict(cls, settings: Settings, data: dict[str, Any]) -> "SoftenerModel":
        state = State(
            stock_kg=float(data.get("stock_kg", settings.capacity_kg)),
            total_regens=int(data.get("total_regens", 0)),
            regens_since_refill=int(data.get("regens_since_refill", 0)),
            last_energy_kwh=data.get("last_energy_kwh"),
            window_date=_d(data.get("window_date")),
            window_energy_kwh=float(data.get("window_energy_kwh", 0.0)),
            window_max_power_w=float(data.get("window_max_power_w", 0.0)),
            window_crossed_at=_dt(data.get("window_crossed_at")),
            evaluated_date=_d(data.get("evaluated_date")),
            last_regen_at=_dt(data.get("last_regen_at")),
            last_refill_at=_dt(data.get("last_refill_at")),
            history=[_dt(h) for h in data.get("history", []) if h],
        )
        return cls(settings, state)
