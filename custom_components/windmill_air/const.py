"""Constants for the Windmill Air Purifier integration."""

from logging import Logger, getLogger

from .models import DEFAULT_MODEL, MODELS

LOGGER: Logger = getLogger(__package__)

DOMAIN = "windmill_air"
# Product-family name (the integration covers every Windmill purifier model);
# the specific model name/number is set per device from models.py.
NAME = "Windmill Air Purifier"

# Config-entry key holding the selected model (see models.py). Absent on entries
# created before models existed, which then fall back to DEFAULT_MODEL.
CONF_MODEL = "model"

# Windmill runs its cloud on a white-labeled Blynk server.
BASE_URL = "https://dashboard.windmillair.com"

CONF_TOKEN = "token"

# --- Pin-mapping options -------------------------------------------------
# All pin values are Blynk datastream names like "v3"; an empty string
# disables the corresponding entity.
CONF_POWER_PIN = "power_pin"
# The mode pin holds the fan speed (1..speed_count) AND the special Eco /
# Sleep values, so it drives both the speed slider and the presets.
CONF_MODE_PIN = "mode_pin"
CONF_SPEED_COUNT = "speed_count"
# Sub-mode pin, only meaningful while the mode pin is set to Sleep.
CONF_SLEEP_SUBMODE_PIN = "sleep_submode_pin"
CONF_AQI_PIN = "aqi_pin"
# The category pin reports a text label (Good/Moderate/…) rather than a number,
# so it is always fetched individually to get the label instead of the raw code.
CONF_AQI_CATEGORY_PIN = "aqi_category_pin"
CONF_PM25_PIN = "pm25_pin"
CONF_CHILD_LOCK_PIN = "child_lock_pin"
CONF_LED_FADE_PIN = "led_fade_pin"
CONF_BEEP_PIN = "beep_pin"
CONF_UPDATE_INTERVAL = "update_interval"

# --- "Auto" preset options -----------------------------------------------
# The device has no native auto mode; the integration emulates one by writing
# a numbered speed to the mode pin based on the AQI reading. These tune that
# mapping (see fan.auto_target_speed) and are exposed via the options flow.
CONF_AUTO_PRESET_ENABLED = "auto_preset_enabled"
# AQI value at/above which auto selects speed 2, 3, 4 respectively (ascending).
CONF_AUTO_THRESHOLD_1 = "auto_threshold_1"
CONF_AUTO_THRESHOLD_2 = "auto_threshold_2"
CONF_AUTO_THRESHOLD_3 = "auto_threshold_3"
# Dead-band (in AQI units) applied around each boundary to stop speed flapping.
CONF_AUTO_HYSTERESIS = "auto_hysteresis"
# Lowest speed auto may select; it never drops below this even at low AQI.
CONF_AUTO_MIN_LEVEL = "auto_min_level"

# --- Defaults --------------------------------------------------------------
# The per-model pin layout / speed count lives in models.py; these module-level
# constants mirror the default model so existing references keep a single source
# of truth. Each is still overridable per config entry via the options flow.
_DEFAULT_MODEL = MODELS[DEFAULT_MODEL]
DEFAULT_POWER_PIN = _DEFAULT_MODEL.power_pin
DEFAULT_MODE_PIN = _DEFAULT_MODEL.mode_pin
DEFAULT_SPEED_COUNT = _DEFAULT_MODEL.speed_count
DEFAULT_SLEEP_SUBMODE_PIN = _DEFAULT_MODEL.sleep_submode_pin
DEFAULT_AQI_PIN = _DEFAULT_MODEL.aqi_pin  # numeric 0-500 (category pin holds the label)
DEFAULT_AQI_CATEGORY_PIN = _DEFAULT_MODEL.aqi_category_pin  # text: Good / Moderate / …
DEFAULT_CHILD_LOCK_PIN = _DEFAULT_MODEL.child_lock_pin
DEFAULT_LED_FADE_PIN = _DEFAULT_MODEL.led_fade_pin
DEFAULT_BEEP_PIN = _DEFAULT_MODEL.beep_pin
DEFAULT_UPDATE_INTERVAL = 30

# --- "Auto" preset defaults ----------------------------------------------
# Boundaries on the 0-500 AQI scale; roughly the Good / Moderate / Unhealthy
# transitions. speed 1 below T1, speed 2 at T1, speed 3 at T2, speed 4 at T3.
DEFAULT_AUTO_PRESET_ENABLED = True
DEFAULT_AUTO_THRESHOLD_1 = 50
DEFAULT_AUTO_THRESHOLD_2 = 100
DEFAULT_AUTO_THRESHOLD_3 = 150
DEFAULT_AUTO_HYSTERESIS = 10
DEFAULT_AUTO_MIN_LEVEL = 1

# --- Mode-pin enum values (device firmware behavior) ---------------------
MODE_ECO = 5
MODE_SLEEP = 6
# Sleep sub-mode values on CONF_SLEEP_SUBMODE_PIN.
SLEEP_WHISPER = 1
SLEEP_WHITE_NOISE = 2

# Must be exactly "auto" (case-insensitive): Home Assistant only wires a fan
# preset to Apple Home's Auto/Manual toggle when it is named "auto".
PRESET_AUTO = "auto"
PRESET_ECO = "Eco"
PRESET_SLEEP_WHISPER = "Sleep: Whisper"
PRESET_SLEEP_WHITE_NOISE = "Sleep: White noise"
