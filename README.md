# Water Softener Refill Sensor (Smart Plug Edition) for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/v/release/vitals5/water-softener-refill-sensor)](https://github.com/vitals5/water-softener-refill-sensor/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Validate Integration](https://github.com/vitals5/water-softener-refill-sensor/actions/workflows/validate.yml/badge.svg)](https://github.com/vitals5/water-softener-refill-sensor/actions/workflows/validate.yml)

A custom Home Assistant integration that monitors **water softener regenerations** and tracks **salt levels** using a **smart plug with power [W] and energy [kWh] metering**. It automatically notifies you when salt needs to be refilled.

Supports **multiple water softener instances**, full **UI configuration via Config Flow & Options Flow**, and is **multilingual** (English & German).

---

## Why Smart Plug Detection?

Traditional water softener tracking often requires plumbing in a dedicated water pulse meter or installing ultrasonic/optical distance sensors inside corrosive brine tanks.

Most modern water softeners (e.g. **Aqmos, Grünbeck, BWT, Clack valves, Fleck/Pentair, Water2Buy, etc.**) are plugged into electrical outlets:
- In standby mode, the electronics consume negligible power (typically **~1–2 W**).
- During regeneration, the motorized control valve cycles through backwash, brine draw, slow rinse, and refill stages, drawing active electrical power (typically **8–30+ W**) and consuming **~0.015–0.06 kWh** of energy.

By plugging your water softener into a smart plug (e.g. Shelly, Zigbee plug, Tapo, Tasmota, etc.), this integration accurately detects regenerations without any plumbing or tank modifications!

---

## How It Works

### 1. Regeneration Detection
- **Time Window:** Water softeners typically regenerate during nighttime hours (default: **02:00 to 03:00 AM**). You can adjust this window to match your softener's schedule.
- **Power & Energy Monitoring:**
  - **Power [W]:** Real-time active power monitoring provides an instant `Regeneration active` binary sensor whenever the valve motor runs.
  - **Energy [kWh]:** Cumulative energy consumption during the time window is tracked.
- **Flexible Detection Modes:**
  - `Energy or power threshold (either)` *(Default / Recommended)*: Detects regeneration if either energy consumed in the window or peak power exceeds threshold.
  - `Both power and energy thresholds`: Requires both peak power and window energy consumption to cross thresholds (extra protection against anomalies).
  - `Energy threshold only`: Detects solely based on energy consumed in the time window (in kWh/Wh).
  - `Power threshold only`: Detects solely based on peak power reached in the time window.
- **Window Finalization:** Evaluated 1 minute after the time window ends. If the criteria are met, exactly **one regeneration cycle** is recorded.

### 2. Salt Stock Calculation
- You configure your brine tank capacity (e.g. 25 kg) and salt used per regeneration (e.g. 1.28 kg).
- Each detected regeneration automatically subtracts the configured amount from the calculated stock.
- The remaining regeneration count and salt level percentage are updated in real time.

### 3. Warnings & Refill Confirmation
- **Low Salt Warning:** When the calculated remaining regenerations drop to or below the warning threshold (default: **3 regenerations**), a persistent notification and problem binary sensor appear.
- **Confirming Refill:**
  - **Single Button Full:** If you filled the tank to capacity, simply press the `Tank full` button.
  - **Partial Refill:** Enter the refilled amount in `Salt amount refilled` (kg) and press `Salt refilled` (or call `refill` service). The amount is added to stock up to the tank capacity.
- **7-Day Hygiene Rule:** Water softeners typically perform a mandatory hygiene regeneration at least every 7 days, even without water demand. The integration calculates `Next regeneration at the latest`. If 7 days pass without a detected regeneration, a `Regeneration overdue` warning is raised.

---

## Installation

### Via HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant.
2. In Home Assistant, open **HACS** → **Integrations** → Click the three dots (⋮) in the top right → **Custom repositories**.
3. Enter repository URL:
   ```
   https://github.com/vitals5/water-softener-refill-sensor
   ```
4. Select category: **Integration**.
5. Click **Add**, find **Water Softener Refill Sensor**, and click **Download**.
6. **Restart Home Assistant**.

### Manual Installation

1. Download the latest release from the [Releases](https://github.com/vitals5/water-softener-refill-sensor/releases) page.
2. Copy the `custom_components/water_softener_refill_sensor` folder into your Home Assistant `<config>/custom_components/` directory.
3. **Restart Home Assistant**.

---

## Configuration

Navigate to **Settings → Devices & Services → Add Integration** and search for **Water Softener Refill Sensor**.

| Field | Description | Default |
|---|---|---|
| **Name** | Device name for the water softener | `Enthärtungsanlage` |
| **Power sensor** | Entity reporting active power in Watts [W] (e.g. smart plug power) | *Required* |
| **Energy sensor** | Entity reporting cumulative energy consumption [kWh or Wh] | *Required* |
| **Power threshold** | Power level in Watts [W] to consider the motor active | `6.0 W` |
| **Energy threshold** | Energy consumed in the time window to count as regeneration | `0.015 kWh` |
| **Detection mode** | Criterion (`energy_or_power`, `both`, `energy_only`, `power_only`) | `energy_or_power` |
| **Brine tank capacity** | Total salt capacity of the tank in kg | `25.0 kg` |
| **Salt per regeneration** | Salt consumed per regeneration cycle in kg | `1.28 kg` |
| **Current salt stock** | Optional initial stock on first setup. Leave empty if tank is full | *Full tank* |
| **Time window from / to** | Time window when regeneration takes place (hours) | `2 to 3 (AM)` |
| **Warn at remaining stock** | Warning threshold in remaining regenerations | `3` |

### Changing Settings Later (Options Flow)
All settings (except the name and initial stock) can be changed anytime by clicking **Configure** on the integration entry in **Devices & Services**.

### Starting Mid-Tank (Calibration)
If your tank is already partially used when setting up:
- Under the device's **Configuration** section, use **Correct last regeneration** to set the timestamp from your softener's display.
- Use **Correct regenerations since refill** to enter the known count since the last full refill; the stock will automatically be calculated (`Capacity - Count × PerRegen`).

---

## Entities Provided

Each configured water softener creates a dedicated Home Assistant device with the following entities:

### Sensors
| Entity | ID Key | Unit / Type | Description |
|---|---|---|---|
| **Total regenerations** | `total_regenerations` | Counter (`total_increasing`) | Total detected regenerations over time |
| **Regenerations since refill** | `regenerations_since_refill` | Counter (`measurement`) | Cycles since the tank was last filled up |
| **Salt stock** | `salt_stock` | `kg` (`weight`) | Current calculated salt stock in kg |
| **Salt level** | `salt_level` | `%` | Calculated salt percentage |
| **Remaining regenerations** | `regenerations_left` | Counter | Number of regenerations remaining before empty |
| **Last regeneration** | `last_regeneration` | Timestamp | Time when last regeneration was detected (includes history of last 10) |
| **Next regeneration due** | `next_regeneration_due` | Timestamp | Latest expected date of next regeneration (7-day hygiene rule) |
| **Last refill** | `last_refill` | Timestamp (Diagnostic) | Date and time when refill was last confirmed |
| **Energy use in time window** | `window_energy` | `kWh` (Diagnostic) | Energy consumed in the current / last evaluation window |
| **Max power in time window** | `window_max_power` | `W` (Diagnostic) | Peak power recorded in the current / last evaluation window |
| **Current power** | `current_power` | `W` (Diagnostic) | Current instantaneous power reading |

### Binary Sensors
| Entity | ID Key | Class | Description |
|---|---|---|---|
| **Refill salt** | `refill_needed` | `problem` | `ON` when salt stock drops to or below the warning threshold |
| **Regeneration overdue** | `regeneration_overdue` | `problem` | `ON` when no regeneration has been detected for > 7 days |
| **Regeneration active** | `regenerating` | `running` | `ON` while active power is at or above the power threshold |

### Controls & Inputs
| Entity | ID Key | Type | Description |
|---|---|---|---|
| **Salt amount refilled** | `refill_amount` | Number (`kg`, box mode) | Enter kilograms refilled. Cleared to 0 upon confirmation |
| **Correct regenerations since refill** | `regenerations_since_refill_input` | Number (Config) | Correct known regenerations since full refill |
| **Salt refilled** | `confirm_refill` | Button | Confirms refill with amount from `refill_amount` |
| **Tank full** | `confirm_full` | Button | Resets stock to full capacity with a single click |
| **Correct last regeneration** | `last_regeneration_input` | DateTime (Config) | Manually set the last regeneration date and time |

---

## Services

The integration provides 5 services in Home Assistant:

### `water_softener_refill_sensor.refill`
Confirms a salt refill with an explicit amount in kg:
```yaml
action: water_softener_refill_sensor.refill
data:
  kg: 25.0
  # config_entry: <entry_id>  # Only required if multiple water softeners are configured
```

### `water_softener_refill_sensor.set_salt_stock`
Directly sets the calculated salt stock to a value in kg:
```yaml
action: water_softener_refill_sensor.set_salt_stock
data:
  kg: 18.5
```

### `water_softener_refill_sensor.add_regeneration`
Manually adds one or more missed regenerations:
```yaml
action: water_softener_refill_sensor.add_regeneration
data:
  count: 1
```

### `water_softener_refill_sensor.set_last_regeneration`
Corrects the timestamp of the last regeneration:
```yaml
action: water_softener_refill_sensor.set_last_regeneration
data:
  datetime: "2026-10-06 02:30:00"
```

### `water_softener_refill_sensor.set_regenerations_since_refill`
Sets known regenerations since full refill (recalculates salt stock):
```yaml
action: water_softener_refill_sensor.set_regenerations_since_refill
data:
  count: 4
```

---

## Multiple Water Softener Instances

You can set up multiple water softeners in the same Home Assistant instance. Each instance runs completely independently with its own settings, entities, persistent storage, and notifications.

When calling services from automations:
- If only one water softener is configured, the `config_entry` parameter is optional.
- If multiple water softeners are configured, specify `config_entry` (or select the target device in the automation editor).

---

## Automation Examples

### Mobile Notification When Salt is Low
```yaml
alias: "Water Softener: Low Salt Alert"
description: "Send push notification when salt needs refilling"
trigger:
  - platform: state
    entity_id: binary_sensor.enthaertungsanlage_refill_needed
    to: "on"
action:
  - action: notify.notify
    data:
      title: "🧂 Water Softener Low on Salt"
      message: >
        The salt stock has reached {{ states('sensor.enthaertungsanlage_salt_stock') }} kg
        ({{ states('sensor.enthaertungsanlage_salt_level') }}%).
        Only {{ states('sensor.enthaertungsanlage_regenerations_left') }} regenerations remaining.
```

### Mobile Notification When Regeneration is Overdue
```yaml
alias: "Water Softener: Hygiene Regeneration Overdue"
description: "Alert if no regeneration was detected for 7 days"
trigger:
  - platform: state
    entity_id: binary_sensor.enthaertungsanlage_regeneration_overdue
    to: "on"
action:
  - action: notify.notify
    data:
      title: "⚠️ Water Softener Regeneration Overdue"
      message: >
        No regeneration has been detected for over 7 days.
        Please check the smart plug connection and water softener display.
```

---

## Dashboard Card Example

You can easily display the water softener on your Lovelace dashboard with an Entities or Mushroom card:

```yaml
type: entities
title: Water Softener
entities:
  - entity: sensor.enthaertungsanlage_salt_stock
    name: Salt Stock
  - entity: sensor.enthaertungsanlage_salt_level
    name: Salt Level
  - entity: sensor.enthaertungsanlage_regenerations_left
    name: Remaining Regenerations
  - entity: binary_sensor.enthaertungsanlage_regenerating
    name: Currently Regenerating
  - entity: binary_sensor.enthaertungsanlage_refill_needed
    name: Refill Needed
  - entity: sensor.enthaertungsanlage_last_regeneration
    name: Last Regeneration
  - entity: number.enthaertungsanlage_refill_amount
    name: Amount Refilled (kg)
  - entity: button.enthaertungsanlage_confirm_refill
    name: Confirm Refill
  - entity: button.enthaertungsanlage_confirm_full
    name: Set Tank Full
```

---

## Development & Testing

The calculation and detection logic is isolated in `custom_components/water_softener_refill_sensor/logic.py` and can be tested without a live Home Assistant installation.

Run the test suite:
```bash
python3 -m unittest discover -s tests -v
```

- `tests/test_logic.py`: Verifies threshold evaluation, power/energy detection modes, hygiene rule, and clamping.
- `tests/test_integration_smoke.py`: Simulates Home Assistant state change events, coordinator updates, notifications, service calls, and restarts.

---

## License

This project is licensed under the [MIT License](LICENSE).
