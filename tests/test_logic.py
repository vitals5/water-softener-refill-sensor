import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import ha_stubs

ha_stubs.install()

from custom_components.water_softener_refill_sensor.const import (
    MODE_BOTH,
    MODE_ENERGY_ONLY,
    MODE_ENERGY_OR_POWER,
    MODE_POWER_ONLY,
)
from custom_components.water_softener_refill_sensor.logic import Settings, SoftenerModel

TZ = ZoneInfo("Europe/Berlin")


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


class RegenerationDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            capacity_kg=25.0,
            per_regen_kg=1.28,
            power_threshold_w=6.0,
            energy_threshold_kwh=0.015,
            detection_mode=MODE_ENERGY_OR_POWER,
            start_hour=2,
            end_hour=3,
            warn_remaining=3,
        )
        self.model = SoftenerModel(self.settings)

    def test_night_with_regeneration_via_energy(self) -> None:
        # Evening before
        self.model.on_energy(100.0, _dt(5, 23, 0))

        # In window (02:00 - 03:00)
        self.model.on_power(1.2, _dt(6, 2, 5))
        self.model.on_energy(100.005, _dt(6, 2, 10))
        self.model.on_power(18.0, _dt(6, 2, 20))
        self.model.on_energy(100.035, _dt(6, 2, 30))  # +0.035 kWh delta > 0.015 threshold
        self.model.on_power(1.5, _dt(6, 2, 50))

        # Close window at 03:01
        events = self.model.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        types = [e["type"] for e in events]
        self.assertIn("window_closed", types)
        self.assertIn("regeneration", types)
        self.assertEqual(self.model.state.total_regens, 1)
        self.assertEqual(self.model.state.regens_since_refill, 1)
        self.assertAlmostEqual(self.model.state.stock_kg, 25.0 - 1.28)

    def test_night_with_regeneration_via_power(self) -> None:
        self.settings.detection_mode = MODE_POWER_ONLY
        self.model = SoftenerModel(self.settings)

        self.model.on_power(1.0, _dt(6, 2, 0))
        self.model.on_power(12.5, _dt(6, 2, 15))  # max power 12.5 W > 6.0 W
        self.model.on_power(1.2, _dt(6, 2, 45))

        events = self.model.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        types = [e["type"] for e in events]
        self.assertIn("regeneration", types)
        self.assertEqual(self.model.state.total_regens, 1)

    def test_detection_modes(self) -> None:
        # Mode: BOTH
        self.settings.detection_mode = MODE_BOTH

        # Case 1: High power, but low energy -> should NOT detect
        m1 = SoftenerModel(self.settings)
        m1.on_energy(10.0, _dt(6, 2, 0))
        m1.on_power(20.0, _dt(6, 2, 10))
        m1.on_energy(10.005, _dt(6, 2, 20))  # delta only 0.005 kWh < 0.015
        events = m1.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        self.assertNotIn("regeneration", [e["type"] for e in events])

        # Case 2: High energy, but low power -> should NOT detect
        m2 = SoftenerModel(self.settings)
        m2.on_energy(10.0, _dt(6, 2, 0))
        m2.on_power(3.0, _dt(6, 2, 10))  # power 3.0 W < 6.0 W
        m2.on_energy(10.050, _dt(6, 2, 20))  # delta 0.050 kWh > 0.015
        events = m2.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        self.assertNotIn("regeneration", [e["type"] for e in events])

        # Case 3: Both high power and high energy -> SHOULD detect
        m3 = SoftenerModel(self.settings)
        m3.on_energy(10.0, _dt(6, 2, 0))
        m3.on_power(20.0, _dt(6, 2, 10))
        m3.on_energy(10.050, _dt(6, 2, 20))
        events = m3.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        self.assertIn("regeneration", [e["type"] for e in events])

    def test_is_regenerating_flag(self) -> None:
        self.model.on_power(2.0, _dt(6, 2, 0))
        self.assertFalse(self.model.is_regenerating)
        self.model.on_power(15.0, _dt(6, 2, 10))
        self.assertTrue(self.model.is_regenerating)
        self.model.on_power(1.5, _dt(6, 2, 50))
        self.assertFalse(self.model.is_regenerating)

    def test_consumption_outside_window_is_ignored(self) -> None:
        self.model.on_energy(100.0, _dt(6, 1, 0))
        self.model.on_energy(101.0, _dt(6, 1, 30))  # heavy consumption outside window
        self.model.on_power(50.0, _dt(6, 1, 30))

        events = self.model.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        self.assertNotIn("regeneration", [e["type"] for e in events])
        self.assertEqual(self.model.state.total_regens, 0)

    def test_quiet_night_records_zero(self) -> None:
        self.model.on_energy(100.0, _dt(6, 0, 0))
        events = self.model.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "window_closed")
        self.assertEqual(events[0]["energy_kwh"], 0.0)
        self.assertEqual(self.model.state.total_regens, 0)

    def test_meter_reset_is_ignored(self) -> None:
        self.model.on_energy(100.0, _dt(6, 2, 10))
        self.model.on_energy(10.0, _dt(6, 2, 20))  # negative jump (e.g. meter replacement)
        events = self.model.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        self.assertNotIn("regeneration", [e["type"] for e in events])

    def test_baseline_only_does_not_count_gap(self) -> None:
        self.model.on_energy(100.0, _dt(6, 1, 0))
        # After reboot, baseline_only=True ignores difference between 100 and 150
        self.model.on_energy(150.0, _dt(6, 2, 10), baseline_only=True)
        events = self.model.evaluate_pending(_dt(6, 3, 1), scheduled=True)
        self.assertNotIn("regeneration", [e["type"] for e in events])

    def test_state_roundtrip(self) -> None:
        self.model.state.total_regens = 5
        self.model.state.stock_kg = 18.5
        self.model.state.last_regen_at = _dt(5, 2, 30)
        data = self.model.to_dict()
        restored = SoftenerModel.from_dict(self.settings, data)
        self.assertEqual(restored.state.total_regens, 5)
        self.assertEqual(restored.state.stock_kg, 18.5)
        self.assertEqual(restored.state.last_regen_at, _dt(5, 2, 30))


class SaltStockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(capacity_kg=25.0, per_regen_kg=1.28, warn_remaining=3)
        self.model = SoftenerModel(self.settings)

    def test_remaining_and_warning(self) -> None:
        self.model.set_stock(3.84)  # 3 * 1.28 -> 3 remaining
        self.assertEqual(self.model.remaining_regens, 3)
        self.assertTrue(self.model.needs_refill)

        self.model.set_stock(5.15)  # 4 * 1.28 = 5.12 -> 4 remaining
        self.assertEqual(self.model.remaining_regens, 4)
        self.assertFalse(self.model.needs_refill)

    def test_refill_requires_positive_amount(self) -> None:
        with self.assertRaises(ValueError):
            self.model.refill(_dt(6, 12, 0), 0)
        with self.assertRaises(ValueError):
            self.model.refill(_dt(6, 12, 0), -5)

    def test_refill_confirms_and_resets(self) -> None:
        self.model.set_stock(2.0)
        self.model.state.regens_since_refill = 18
        added = self.model.refill(_dt(6, 12, 0), 23.0)  # Total 25.0 (full)
        self.assertEqual(added, 23.0)
        self.assertEqual(self.model.state.stock_kg, 25.0)
        self.assertEqual(self.model.state.regens_since_refill, 0)
        self.assertFalse(self.model.needs_refill)

    def test_refill_full_sets_full_and_resets(self) -> None:
        self.model.set_stock(5.0)
        self.model.state.regens_since_refill = 15
        added = self.model.refill_full(_dt(6, 12, 0))
        self.assertEqual(added, 20.0)
        self.assertEqual(self.model.state.stock_kg, 25.0)
        self.assertEqual(self.model.state.regens_since_refill, 0)

    def test_partial_refill_and_clamp(self) -> None:
        self.model.set_stock(10.0)
        self.model.state.regens_since_refill = 10
        # Refill 5 kg -> 15 kg (not full yet)
        added = self.model.refill(_dt(6, 12, 0), 5.0)
        self.assertEqual(added, 5.0)
        self.assertEqual(self.model.state.stock_kg, 15.0)
        self.assertEqual(self.model.state.regens_since_refill, 10)  # counter remains

        # Overfilling clamps to 25.0
        added_over = self.model.refill(_dt(6, 12, 0), 20.0)
        self.assertEqual(added_over, 10.0)
        self.assertEqual(self.model.state.stock_kg, 25.0)
        self.assertEqual(self.model.state.regens_since_refill, 0)

    def test_set_regens_since_refill_recalculates_stock(self) -> None:
        self.model.set_regens_since_refill(5)
        self.assertEqual(self.model.state.regens_since_refill, 5)
        self.assertAlmostEqual(self.model.state.stock_kg, 25.0 - 5 * 1.28)


class HygieneRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(start_hour=2, end_hour=3)
        self.model = SoftenerModel(self.settings)

    def test_next_due_seven_days_later(self) -> None:
        self.model.state.last_regen_at = _dt(1, 2, 30)
        due = self.model.next_regen_due(TZ)
        self.assertEqual(due, _dt(8, 2, 0))

    def test_overdue_after_window_of_due_day(self) -> None:
        self.model.state.last_regen_at = _dt(1, 2, 30)
        # Before window end on due day (Oct 8 03:01)
        self.assertFalse(self.model.regen_overdue(_dt(8, 3, 0)))
        # After window end on due day
        self.assertTrue(self.model.regen_overdue(_dt(8, 3, 2)))

    def test_regeneration_on_due_day_clears_overdue(self) -> None:
        self.model.state.last_regen_at = _dt(1, 2, 30)
        self.assertTrue(self.model.regen_overdue(_dt(8, 3, 2)))

        # New regeneration registered
        self.model.add_manual_regeneration(_dt(8, 2, 30))
        self.assertFalse(self.model.regen_overdue(_dt(8, 3, 2)))


if __name__ == "__main__":
    unittest.main()
