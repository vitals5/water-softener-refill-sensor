# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-10-07

### Added
- Initial release of Water Softener Refill Sensor (Smart Plug Edition).
- Regeneration detection using active power [W] and cumulative energy [kWh] from smart plugs.
- 4 Detection modes: `energy_or_power`, `both`, `energy_only`, and `power_only`.
- Real-time `Regeneration active` (`regenerating`) binary sensor.
- Salt stock calculation based on configurable capacity and salt consumption per regeneration.
- 7-day hygiene rule tracking and overdue notification.
- UI Configuration and Options Flow support in Home Assistant.
- Multi-instance support (multiple water softeners per Home Assistant instance).
- 5 component services: `refill`, `set_salt_stock`, `add_regeneration`, `set_last_regeneration`, and `set_regenerations_since_refill`.
- English and German translations for UI, entities, services, and notifications.
- Comprehensive test suite for logic and Home Assistant integrations.
