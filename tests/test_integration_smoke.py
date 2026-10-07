"""Integration smoke tests using Home Assistant stubs (ha_stubs.py).

Simulates a full night scenario:
Smart plug power & energy readings -> Regeneration detected -> Salt stock updated -> Low salt alert -> Refill confirmation.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ha_stubs

ha_stubs.install()
from ha_stubs import TZ, FakeDt, FakeNotifications, FakeStore

from custom_components.water_softener_refill_sensor import (
    _manager_for,
    async_remove_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.water_softener_refill_sensor import binary_sensor as bs_mod
from custom_components.water_softener_refill_sensor import button as btn_mod
from custom_components.water_softener_refill_sensor import config_flow
from custom_components.water_softener_refill_sensor import datetime as dt_mod
from custom_components.water_softener_refill_sensor import number as num_mod
from custom_components.water_softener_refill_sensor import sensor as sensor_mod
from homeassistant.const import CONF_NAME

from custom_components.water_softener_refill_sensor.const import (
    CONF_CAPACITY_KG,
    CONF_DETECTION_MODE,
    CONF_ENERGY_ENTITY,
    CONF_ENERGY_THRESHOLD_KWH,
    CONF_PER_REGEN_KG,
    CONF_POWER_ENTITY,
    CONF_POWER_THRESHOLD_W,
    CONF_WARN_REMAINING,
    CONF_WINDOW_END,
    CONF_WINDOW_START,
    DOMAIN,
    MODE_BOTH,
    MODE_ENERGY_OR_POWER,
)
from custom_components.water_softener_refill_sensor.manager import SoftenerManager


def local(day: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 10, day, hh, mm, tzinfo=TZ)


class FakeState:
    def __init__(self, state: str, unit: str = "W", when: datetime | None = None) -> None:
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit else {}
        self.last_updated = when or FakeDt._now


class FakeStates:
    def __init__(self) -> None:
        self._s: dict[str, FakeState] = {}

    def get(self, entity_id: str) -> FakeState | None:
        return self._s.get(entity_id)

    def set(self, entity_id: str, state: FakeState) -> None:
        self._s[entity_id] = state


class FakeHass:
    def __init__(self) -> None:
        self.data: dict = {}
        self.config = types.SimpleNamespace(language="de")
        self.states = FakeStates()
        self.state_cbs: list = []
        self.time_cbs: list = []
        self.services = types.SimpleNamespace(registered={}, async_register=self._register)
        calls: list = []
        self.calls = calls

        async def forward(entry, platforms):
            calls.append(("forward", list(platforms)))

        async def unload(entry, platforms):
            return True

        async def reload(entry_id):
            calls.append(("reload", entry_id))

        self.config_entries = types.SimpleNamespace(
            async_forward_entry_setups=forward,
            async_unload_platforms=unload,
            async_reload=reload,
        )

    def _register(self, domain, name, handler, schema=None):
        self.services.registered[name] = handler


class FakeEntry:
    def __init__(self, **data) -> None:
        self.entry_id = "abc123"
        self.title = "Enthärtungsanlage"
        self.data = {
            CONF_NAME: "Enthärtungsanlage",
            CONF_POWER_ENTITY: "sensor.steckdose_power",
            CONF_ENERGY_ENTITY: "sensor.steckdose_energy",
            CONF_POWER_THRESHOLD_W: 6.0,
            CONF_ENERGY_THRESHOLD_KWH: 0.015,
            CONF_DETECTION_MODE: MODE_ENERGY_OR_POWER,
            CONF_CAPACITY_KG: 17.0,
            CONF_PER_REGEN_KG: 4.0,
            CONF_WINDOW_START: 2,
            CONF_WINDOW_END: 3,
            CONF_WARN_REMAINING: 3,
        }
        self.data.update(data)
        self.options = {}

    def add_update_listener(self, fn):
        return lambda: None

    def async_on_unload(self, fn):
        pass


def push_power(hass: FakeHass, value: float, when: datetime, unit: str = "W") -> None:
    FakeDt._now = when
    state = FakeState(str(value), unit, when)
    hass.states.set("sensor.steckdose_power", state)
    for ids, cb in hass.state_cbs:
        if "sensor.steckdose_power" in ids:
            cb(types.SimpleNamespace(data={"new_state": state}))


def push_energy(hass: FakeHass, value: float, when: datetime, unit: str = "kWh") -> None:
    FakeDt._now = when
    state = FakeState(str(value), unit, when)
    hass.states.set("sensor.steckdose_energy", state)
    for ids, cb in hass.state_cbs:
        if "sensor.steckdose_energy" in ids:
            cb(types.SimpleNamespace(data={"new_state": state}))


def window_end(hass: FakeHass, when: datetime) -> None:
    FakeDt._now = when
    for hour, minute, second, cb in hass.time_cbs:
        cb(when)


class ConfigFlowHelpers(unittest.TestCase):
    def test_number_selector_never_gets_unit_none(self) -> None:
        sel = config_flow._number(1, 10, 1, None)
        self.assertNotIn("unit_of_measurement", sel.config)
        sel_with_unit = config_flow._number(1, 10, 1, "kg")
        self.assertEqual(sel_with_unit.config["unit_of_measurement"], "kg")

    def test_schema_builds(self) -> None:
        schema1 = config_flow._schema(True, {})
        self.assertIsNotNone(schema1)
        schema2 = config_flow._schema(False, {})
        self.assertIsNotNone(schema2)

    def test_normalize_and_validate(self) -> None:
        user_input = {
            CONF_NAME: "Weichwasser",
            CONF_POWER_ENTITY: "sensor.plug_power",
            CONF_ENERGY_ENTITY: "sensor.plug_energy",
            CONF_POWER_THRESHOLD_W: "8.5",
            CONF_ENERGY_THRESHOLD_KWH: "0.02",
            CONF_DETECTION_MODE: MODE_ENERGY_OR_POWER,
            CONF_CAPACITY_KG: "25.0",
            CONF_PER_REGEN_KG: "1.28",
            CONF_WINDOW_START: "2",
            CONF_WINDOW_END: "3",
            CONF_WARN_REMAINING: "3",
        }
        normalized = config_flow._normalize(user_input)
        self.assertEqual(normalized[CONF_POWER_THRESHOLD_W], 8.5)
        self.assertEqual(normalized[CONF_ENERGY_THRESHOLD_KWH], 0.02)
        self.assertEqual(normalized[CONF_CAPACITY_KG], 25.0)
        self.assertEqual(normalized[CONF_WINDOW_START], 2)
        errors = config_flow._validate(normalized)
        self.assertEqual(errors, {})

        # Window invalid
        bad_window = dict(normalized, **{CONF_WINDOW_START: 4, CONF_WINDOW_END: 3})
        self.assertEqual(config_flow._validate(bad_window)["base"], "window_invalid")

        # Per regen too large
        bad_regen = dict(normalized, **{CONF_PER_REGEN_KG: 30.0})
        self.assertEqual(config_flow._validate(bad_regen)["base"], "per_regen_too_large")

        # Power threshold invalid
        bad_power = dict(normalized, **{CONF_POWER_THRESHOLD_W: 0.0})
        self.assertEqual(config_flow._validate(bad_power)["base"], "power_threshold_invalid")


class NightScenario(unittest.TestCase):
    def setUp(self) -> None:
        FakeStore.DATA.clear()
        FakeNotifications.active.clear()
        FakeNotifications.log.clear()

    def start(self, **entry_kw) -> tuple[FakeHass, FakeEntry]:
        hass = FakeHass()
        entry = FakeEntry(**entry_kw)
        FakeDt._now = local(5, 22)
        hass.states.set("sensor.steckdose_power", FakeState("1.2", "W", local(5, 21)))
        hass.states.set("sensor.steckdose_energy", FakeState("50.000", "kWh", local(5, 21)))
        return hass, entry

    def test_full_night_with_low_salt_notification_and_confirmation(self) -> None:
        hass, entry = self.start()
        asyncio.run(self._night(hass, entry))

    async def _night(self, hass: FakeHass, entry: FakeEntry) -> None:
        await async_setup(hass, {})
        await async_setup_entry(hass, entry)
        mgr = hass.data[DOMAIN]["abc123"]

        self.assertEqual(mgr.coordinator.data["regenerations_left"], 4)
        self.assertEqual(FakeNotifications.active, {})

        # Scheduled evaluation at 03:01:00
        self.assertEqual([(h, m, s) for h, m, s, _ in hass.time_cbs], [(3, 1, 0)])

        # Before window: standby power
        push_power(hass, 1.2, local(6, 1, 30))
        push_energy(hass, 50.000, local(6, 1, 30))

        # Regeneration begins at 02:10: power spikes to 18 W
        push_power(hass, 18.0, local(6, 2, 10))
        self.assertTrue(mgr.coordinator.data["is_regenerating"])

        # Energy accumulates +0.035 kWh
        push_energy(hass, 50.035, local(6, 2, 30))

        # Regeneration ends: power drops to 1.1 W
        push_power(hass, 1.1, local(6, 2, 50))
        self.assertFalse(mgr.coordinator.data["is_regenerating"])

        # Prior to window close: 0 regens counted yet
        self.assertEqual(mgr.coordinator.data["total_regenerations"], 0)
        self.assertAlmostEqual(mgr.coordinator.data["window_energy_kwh"], 0.035)
        self.assertEqual(mgr.coordinator.data["window_max_power_w"], 18.0)

        # Window evaluation at 03:01
        window_end(hass, local(6, 3, 1))

        d = mgr.coordinator.data
        self.assertEqual(d["total_regenerations"], 1)
        self.assertEqual(d["salt_stock_kg"], 13.0)  # 17 - 4 = 13 kg
        self.assertEqual(d["regenerations_left"], 3)
        self.assertTrue(d["refill_needed"])

        # Low salt notification created
        note = FakeNotifications.active["water_softener_refill_sensor_abc123_low_salt"]
        self.assertIn("3 Regenerationen", note["message"])
        self.assertIn("13.0 kg von 17.0 kg", note["message"])

        # Verify entities
        values = {}
        for desc in sensor_mod.SENSORS:
            ent = sensor_mod.EnthaertungSensor(mgr.coordinator, entry, desc)
            values[desc.key] = ent.native_value
        self.assertEqual(values["total_regenerations"], 1)
        self.assertEqual(values["salt_stock"], 13.0)
        self.assertEqual(values["regenerations_left"], 3)
        self.assertEqual(values["window_energy"], 0.035)
        self.assertEqual(values["window_max_power"], 18.0)

        flag = bs_mod.RefillNeededBinarySensor(mgr.coordinator, entry)
        self.assertTrue(flag.is_on)

        running_flag = bs_mod.RegeneratingBinarySensor(mgr.coordinator, entry)
        self.assertFalse(running_flag.is_on)

        # Confirm refill flow
        button = btn_mod.ConfirmRefillButton(mgr, entry)
        amount = num_mod.RefillAmountNumber(mgr, entry)
        self.assertEqual(amount.native_value, 0.0)

        # Button press without amount fails
        with self.assertRaises(Exception):
            await button.async_press()

        # Partial refill of 2 kg -> stock = 15 kg (still <= 3 remaining regens warning)
        await amount.async_set_native_value(2.0)
        await button.async_press()
        self.assertEqual(mgr.coordinator.data["salt_stock_kg"], 15.0)
        self.assertIn("water_softener_refill_sensor_abc123_low_salt", FakeNotifications.active)
        self.assertTrue(flag.is_on)

        # Full refill of 4 kg -> clamped to 17 kg -> warning cleared
        await amount.async_set_native_value(4.0)
        await button.async_press()
        self.assertEqual(FakeNotifications.active, {})
        self.assertFalse(flag.is_on)
        self.assertEqual(mgr.coordinator.data["salt_stock_kg"], 17.0)
        self.assertEqual(mgr.coordinator.data["regenerations_since_refill"], 0)

    def test_english_notification(self) -> None:
        hass, entry = self.start()
        hass.config.language = "en"
        asyncio.run(self._english(hass, entry))

    async def _english(self, hass: FakeHass, entry: FakeEntry) -> None:
        await async_setup(hass, {})
        await async_setup_entry(hass, entry)
        mgr = hass.data[DOMAIN]["abc123"]

        push_power(hass, 15.0, local(6, 2, 20))
        push_energy(hass, 50.040, local(6, 2, 30))
        window_end(hass, local(6, 3, 1))

        note = FakeNotifications.active["water_softener_refill_sensor_abc123_low_salt"]
        self.assertEqual(note["title"], "Refill salt")
        self.assertIn("3 more regenerations", note["message"])

    def test_overdue_notification(self) -> None:
        hass, entry = self.start()
        asyncio.run(self._overdue(hass, entry))

    async def _overdue(self, hass: FakeHass, entry: FakeEntry) -> None:
        await async_setup(hass, {})
        await async_setup_entry(hass, entry)
        mgr = hass.data[DOMAIN]["abc123"]

        # Last regen was on Oct 1
        await mgr.async_set_last_regeneration(local(1, 2, 30))
        # Now is Oct 8 at 03:02 (window ended on due day Oct 8)
        FakeDt._now = local(8, 3, 2)
        window_end(hass, local(8, 3, 2))

        self.assertIn("water_softener_refill_sensor_abc123_overdue", FakeNotifications.active)
        overdue_sensor = bs_mod.RegenerationOverdueBinarySensor(mgr.coordinator, entry)
        self.assertTrue(overdue_sensor.is_on)

    def test_unit_conversions(self) -> None:
        hass, entry = self.start()
        asyncio.run(self._units(hass, entry))

    async def _units(self, hass: FakeHass, entry: FakeEntry) -> None:
        await async_setup(hass, {})
        await async_setup_entry(hass, entry)
        mgr = hass.data[DOMAIN]["abc123"]

        # Power in kW -> 0.02 kW = 20 W
        push_power(hass, 0.02, local(6, 2, 10), unit="kW")
        self.assertEqual(mgr.coordinator.data["current_power_w"], 20.0)

        # Energy in Wh -> 50035 Wh = 50.035 kWh
        push_energy(hass, 50035, local(6, 2, 20), unit="Wh")
        self.assertAlmostEqual(mgr.coordinator.data["window_energy_kwh"], 0.035)

    def test_services(self) -> None:
        hass, entry = self.start()
        asyncio.run(self._services(hass, entry))

    async def _services(self, hass: FakeHass, entry: FakeEntry) -> None:
        await async_setup(hass, {})
        await async_setup_entry(hass, entry)
        mgr = hass.data[DOMAIN]["abc123"]

        # refill service
        await hass.services.registered["refill"](
            types.SimpleNamespace(data={"kg": 5.0, "config_entry": "abc123"})
        )
        self.assertEqual(mgr.coordinator.data["salt_stock_kg"], 17.0)

        # set_salt_stock service
        await hass.services.registered["set_salt_stock"](
            types.SimpleNamespace(data={"kg": 10.0, "config_entry": "abc123"})
        )
        self.assertEqual(mgr.coordinator.data["salt_stock_kg"], 10.0)

        # add_regeneration service
        await hass.services.registered["add_regeneration"](
            types.SimpleNamespace(data={"count": 1, "config_entry": "abc123"})
        )
        self.assertEqual(mgr.coordinator.data["total_regenerations"], 1)
        self.assertEqual(mgr.coordinator.data["salt_stock_kg"], 6.0)

        # set_regenerations_since_refill service
        await hass.services.registered["set_regenerations_since_refill"](
            types.SimpleNamespace(data={"count": 2, "config_entry": "abc123"})
        )
        self.assertEqual(mgr.coordinator.data["regenerations_since_refill"], 2)
        self.assertEqual(mgr.coordinator.data["salt_stock_kg"], 9.0)  # 17 - 2*4 = 9 kg

    def test_multiple_instances(self) -> None:
        hass = FakeHass()
        entry1 = FakeEntry(name="Softener 1")
        entry1.entry_id = "softener_1"
        entry2 = FakeEntry(name="Softener 2")
        entry2.entry_id = "softener_2"

        asyncio.run(self._multi(hass, entry1, entry2))

    async def _multi(self, hass: FakeHass, entry1: FakeEntry, entry2: FakeEntry) -> None:
        await async_setup(hass, {})
        await async_setup_entry(hass, entry1)
        await async_setup_entry(hass, entry2)

        mgr1 = _manager_for(hass, types.SimpleNamespace(data={"config_entry": "softener_1"}))
        mgr2 = _manager_for(hass, types.SimpleNamespace(data={"config_entry": "softener_2"}))
        self.assertEqual(mgr1.entry.entry_id, "softener_1")
        self.assertEqual(mgr2.entry.entry_id, "softener_2")

        # Calling without config_entry when 2 instances exist raises error
        with self.assertRaises(Exception):
            _manager_for(hass, types.SimpleNamespace(data={}))

    def test_catch_up_after_restart(self) -> None:
        hass = FakeHass()
        entry = FakeEntry()
        # Save a state in store where window had 0.035 kWh usage but was not evaluated
        FakeStore.DATA["water_softener_refill_sensor.abc123"] = {
            "stock_kg": 17.0,
            "total_regens": 0,
            "regens_since_refill": 0,
            "last_energy_kwh": 50.035,
            "window_date": "2026-10-06",
            "window_energy_kwh": 0.035,
            "window_max_power_w": 18.0,
            "window_crossed_at": "2026-10-06T02:20:00+02:00",
            "evaluated_date": None,
            "last_regen_at": None,
            "last_refill_at": None,
            "history": [],
        }
        # Start HA in the morning at 08:00
        FakeDt._now = local(6, 8, 0)
        asyncio.run(self._catchup(hass, entry))

    async def _catchup(self, hass: FakeHass, entry: FakeEntry) -> None:
        await async_setup(hass, {})
        await async_setup_entry(hass, entry)
        mgr = hass.data[DOMAIN]["abc123"]
        # Pending window was finalized on start
        self.assertEqual(mgr.coordinator.data["total_regenerations"], 1)
        self.assertEqual(mgr.coordinator.data["salt_stock_kg"], 13.0)


if __name__ == "__main__":
    unittest.main()
