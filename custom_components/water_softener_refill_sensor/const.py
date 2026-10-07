"""Constants for the Water Softener Refill Sensor (Smart Plug Edition)."""
from homeassistant.const import Platform

DOMAIN = "water_softener_refill_sensor"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.DATETIME]

CONF_POWER_ENTITY = "power_entity"
CONF_ENERGY_ENTITY = "energy_entity"
CONF_POWER_THRESHOLD_W = "power_threshold_w"
CONF_ENERGY_THRESHOLD_KWH = "energy_threshold_kwh"
CONF_DETECTION_MODE = "detection_mode"
CONF_CAPACITY_KG = "capacity_kg"
CONF_PER_REGEN_KG = "per_regen_kg"
CONF_INITIAL_STOCK_KG = "initial_stock_kg"
CONF_WINDOW_START = "window_start_hour"
CONF_WINDOW_END = "window_end_hour"
CONF_WARN_REMAINING = "warn_remaining"

DEFAULT_NAME = "Enthärtungsanlage"
DEFAULT_POWER_THRESHOLD_W = 6.0
DEFAULT_ENERGY_THRESHOLD_KWH = 0.015
DEFAULT_DETECTION_MODE = "energy_or_power"
DEFAULT_CAPACITY_KG = 25.0
DEFAULT_PER_REGEN_KG = 1.28
DEFAULT_WINDOW_START = 2
DEFAULT_WINDOW_END = 3
DEFAULT_WARN_REMAINING = 3

MODE_ENERGY_OR_POWER = "energy_or_power"
MODE_BOTH = "both"
MODE_ENERGY_ONLY = "energy_only"
MODE_POWER_ONLY = "power_only"

DETECTION_MODES = [
    MODE_ENERGY_OR_POWER,
    MODE_BOTH,
    MODE_ENERGY_ONLY,
    MODE_POWER_ONLY,
]

ATTR_CONFIG_ENTRY = "config_entry"
ATTR_KG = "kg"
ATTR_COUNT = "count"
ATTR_DATETIME = "datetime"

SERVICE_REFILL = "refill"
SERVICE_SET_STOCK = "set_salt_stock"
SERVICE_ADD_REGENERATION = "add_regeneration"
SERVICE_SET_LAST_REGENERATION = "set_last_regeneration"
SERVICE_SET_REGENS_SINCE_REFILL = "set_regenerations_since_refill"

STORAGE_VERSION = 1
SAVE_DELAY = 30  # seconds


def storage_key(entry_id: str) -> str:
    """Generate storage key for a config entry."""
    return f"{DOMAIN}.{entry_id}"


def notification_id(entry_id: str) -> str:
    """Generate notification ID for low salt alert."""
    return f"{DOMAIN}_{entry_id}_low_salt"


def overdue_notification_id(entry_id: str) -> str:
    """Generate notification ID for overdue regeneration alert."""
    return f"{DOMAIN}_{entry_id}_overdue"
