"""Fan entity for the Windmill Air Purifier.

The purifier exposes a single "mode" datastream (V3 by default) that holds
both the numbered fan speeds and the special Eco / Sleep values:

    1..speed_count -> fan speed levels        -> percentage slider
    MODE_ECO (5)   -> Eco                      -> preset
    MODE_SLEEP (6) -> Sleep                    -> preset, with a sub-mode pin
                                                  (V4: Whisper / White noise)

There is no hardware "auto" value on V3, so the "auto" preset is emulated in
software: engaged-state is tracked on the entity, and while engaged the
integration writes a numbered speed to V3 on every coordinator update, chosen
from the AQI reading (V1) with hysteresis so it does not flap between speeds.
"""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .const import (
    CONF_AQI_CATEGORY_PIN,
    CONF_AUTO_HYSTERESIS,
    CONF_AUTO_MIN_LEVEL,
    CONF_AUTO_PRESET_ENABLED,
    CONF_AUTO_THRESHOLD_1,
    CONF_AUTO_THRESHOLD_2,
    CONF_AUTO_THRESHOLD_3,
    CONF_MODE_PIN,
    CONF_POWER_PIN,
    CONF_SLEEP_SUBMODE_PIN,
    CONF_SPEED_COUNT,
    DEFAULT_AUTO_HYSTERESIS,
    DEFAULT_AUTO_MIN_LEVEL,
    DEFAULT_AUTO_PRESET_ENABLED,
    DEFAULT_AUTO_THRESHOLD_1,
    DEFAULT_AUTO_THRESHOLD_2,
    DEFAULT_AUTO_THRESHOLD_3,
    DOMAIN,
    MODE_ECO,
    MODE_SLEEP,
    PRESET_AUTO,
    PRESET_ECO,
    PRESET_SLEEP_WHISPER,
    PRESET_SLEEP_WHITE_NOISE,
    SLEEP_WHISPER,
    SLEEP_WHITE_NOISE,
)
from .coordinator import WindmillCoordinator
from .entity import WindmillEntity
from .util import as_bool, as_int


def auto_target_speed(
    aqi: int,
    thresholds: list[int],
    speed_count: int,
    current: int | None,
    hysteresis: int,
    min_level: int = 1,
) -> int:
    """Pick a fan speed (1..speed_count) for an AQI reading, with hysteresis.

    ``thresholds`` is an ascending list of AQI boundaries: the naive speed is
    ``1 + (how many thresholds the AQI meets)``, clamped to ``speed_count``.
    ``current`` is the speed auto last commanded (``None`` on first engage).
    ``min_level`` floors the result: auto never selects below it, however low
    the AQI.

    Hysteresis is applied on the way **down only**, so the purifier ramps up
    promptly and is slow to ease off: a step **up** happens as soon as the AQI
    reaches a threshold, while a step **down** needs the AQI to fall
    ``hysteresis`` below the boundary; in between, the speed holds.
    """
    floor = max(1, min(min_level, speed_count))
    if not thresholds:
        return floor
    top = len(thresholds) - 1
    naive = 1 + sum(1 for t in thresholds if aqi >= t)
    # Flooring here (not on the return) means at the floor naive == current,
    # so hysteresis math above the floor still uses real boundaries and the
    # speed can never oscillate at or below the floor.
    naive = max(floor, min(naive, speed_count))
    if current is None:
        return naive
    current = max(floor, min(current, speed_count))
    if naive > current:
        # Rising: step up as soon as the AQI clears the threshold (no dead-band).
        return naive
    if naive < current:
        # Falling: thresholds[current - 2] is the boundary between current-1 and
        # current (clamped for speed counts beyond the number of thresholds).
        # Only step down once the AQI drops a full hysteresis below it.
        boundary = thresholds[min(current - 2, top)]
        return naive if aqi < boundary - hysteresis else current
    return current


# Windmill's air-quality *status* text maps to these representative AQI values
# (band midpoints), so it can drive `auto_target_speed` through the same numeric
# thresholds. The device uses Good / Moderate / Bad / Unhealthy (per its manual);
# the extra rows keep other AQI wordings working. Checked most-specific first so
# e.g. "very unhealthy" isn't caught by the plain "unhealthy" rule.
_CATEGORY_AQI: list[tuple[str, int]] = [
    ("hazard", 400),
    ("very unhealthy", 250),
    ("sensitive", 125),  # "Unhealthy for Sensitive Groups"
    ("unhealthy", 175),  # Windmill: 151+
    ("bad", 125),  # Windmill: 101-150
    ("moderate", 75),  # Windmill: 51-100
    ("good", 25),  # Windmill: 0-50
]


def category_to_aqi(label: str | None) -> int | None:
    """Map an air-quality status label to a representative AQI, or None."""
    if not label:
        return None
    lowered = str(label).strip().lower()
    for keyword, aqi in _CATEGORY_AQI:
        if keyword in lowered:
            return aqi
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WindmillCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([WindmillFan(coordinator)])


class WindmillFan(WindmillEntity, FanEntity):
    """The purifier: power, 4 fan speeds, and Eco / Sleep presets."""

    _attr_name = None  # takes the device name
    _enable_turn_on_off_backwards_compatibility = False

    def __init__(self, coordinator: WindmillCoordinator) -> None:
        super().__init__(coordinator, "fan")
        options = coordinator.config_entry.options
        model = coordinator.model
        self._power_pin: str = options.get(CONF_POWER_PIN, model.power_pin)
        self._mode_pin: str = options.get(CONF_MODE_PIN, model.mode_pin)
        self._submode_pin: str = options.get(
            CONF_SLEEP_SUBMODE_PIN, model.sleep_submode_pin
        )
        # Clamp to MODE_ECO - 1: a speed at the Eco (5) / Sleep (6) enum value
        # would make the top of the slider write Eco instead of a fan speed.
        self._speed_count: int = max(
            1,
            min(
                int(options.get(CONF_SPEED_COUNT, model.speed_count)),
                MODE_ECO - 1,
            ),
        )
        # Auto follows the device's air-quality category (Good/Moderate/Bad/
        # Unhealthy) — the numeric AQI pin isn't reliable across units.
        self._aqi_category_pin: str = options.get(
            CONF_AQI_CATEGORY_PIN, model.aqi_category_pin
        )

        # --- Virtual "auto" preset state and tuning ---
        self._auto_enabled: bool = bool(
            options.get(CONF_AUTO_PRESET_ENABLED, DEFAULT_AUTO_PRESET_ENABLED)
        )
        self._auto_thresholds: list[int] = sorted(
            int(options.get(key, default))
            for key, default in (
                (CONF_AUTO_THRESHOLD_1, DEFAULT_AUTO_THRESHOLD_1),
                (CONF_AUTO_THRESHOLD_2, DEFAULT_AUTO_THRESHOLD_2),
                (CONF_AUTO_THRESHOLD_3, DEFAULT_AUTO_THRESHOLD_3),
            )
        )
        self._auto_hysteresis: int = int(
            options.get(CONF_AUTO_HYSTERESIS, DEFAULT_AUTO_HYSTERESIS)
        )
        # Clamp to the (already-clamped) speed count so a stored floor above a
        # smaller speed count can't push auto past the top of the slider.
        self._auto_min_level: int = max(
            1,
            min(
                int(options.get(CONF_AUTO_MIN_LEVEL, DEFAULT_AUTO_MIN_LEVEL)),
                self._speed_count,
            ),
        )
        # "auto" has no V3 value: track it here, plus the speed we last drove.
        self._auto_engaged = False
        self._auto_speed: int | None = None

        self._attr_supported_features = (
            FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
            | FanEntityFeature.SET_SPEED
            | FanEntityFeature.PRESET_MODE
        )
        # "auto" first so Apple Home folds it into the Auto/Manual toggle.
        # It needs the air-quality category pin to react to.
        presets = (
            [PRESET_AUTO]
            if (self._auto_enabled and self._aqi_category_pin)
            else []
        )
        presets.append(PRESET_ECO)
        if self._submode_pin:
            presets += [PRESET_SLEEP_WHISPER, PRESET_SLEEP_WHITE_NOISE]
        self._attr_preset_modes = presets

    @property
    def speed_count(self) -> int:
        return self._speed_count

    def _mode(self) -> int | None:
        return as_int(self.coordinator.pin_value(self._mode_pin))

    @property
    def is_on(self) -> bool | None:
        return as_bool(self.coordinator.pin_value(self._power_pin))

    @property
    def percentage(self) -> int | None:
        if self.is_on is False:
            return 0
        mode = self._mode()
        if mode is None:
            return None
        if 1 <= mode <= self._speed_count:
            return ranged_value_to_percentage((1, self._speed_count), mode)
        # Eco / Sleep are presets, not numbered speeds.
        return None

    @property
    def preset_mode(self) -> str | None:
        if self.is_on is False:
            return None
        # "auto" is virtual: report it while engaged even though V3 holds a
        # numbered speed (which still drives the percentage slider).
        if self._auto_engaged:
            return PRESET_AUTO
        mode = self._mode()
        if mode == MODE_ECO:
            return PRESET_ECO
        if mode == MODE_SLEEP:
            if not self._submode_pin:
                return None
            sub = as_int(self.coordinator.pin_value(self._submode_pin))
            if sub == SLEEP_WHITE_NOISE:
                return PRESET_SLEEP_WHITE_NOISE
            return PRESET_SLEEP_WHISPER
        return None

    async def _write(self, pin: str, value: Any) -> None:
        await self.coordinator.api.set_pin(pin, value)
        self.coordinator.set_pin_optimistic(pin, value)

    @callback
    def _handle_coordinator_update(self) -> None:
        # While "auto" is engaged, re-derive the speed from the latest AQI on
        # every update (poll or optimistic write) before notifying HA.
        if self._auto_engaged and self.is_on:
            self._apply_auto_speed()
        super()._handle_coordinator_update()

    def _current_aqi(self) -> int | None:
        """AQI (derived from the air-quality category) that auto reacts to."""
        return category_to_aqi(self.coordinator.pin_value(self._aqi_category_pin))

    def _apply_auto_speed(self) -> None:
        """Drive V3 to the AQI-appropriate speed if it needs to change."""
        aqi = self._current_aqi()
        if aqi is None:
            return
        target = auto_target_speed(
            aqi,
            self._auto_thresholds,
            self._speed_count,
            self._auto_speed,
            self._auto_hysteresis,
            min_level=self._auto_min_level,
        )
        self._auto_speed = target
        # Idempotent: only write when V3 differs, so the optimistic-update
        # loop (set_pin_optimistic -> listeners -> here) settles immediately.
        if self._mode() != target:
            self.hass.async_create_task(self._write(self._mode_pin, target))

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        await self._write(self._power_pin, 1)
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._auto_engaged = False  # powering off exits auto
        await self._write(self._power_pin, 0)
        await self.coordinator.async_request_refresh()

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self.async_turn_off()
            return
        self._auto_engaged = False  # a manual speed exits auto
        if self.is_on is False:
            await self._write(self._power_pin, 1)
        # Writing a numbered speed to the mode pin leaves Eco / Sleep.
        level = math.ceil(
            percentage_to_ranged_value((1, self._speed_count), percentage)
        )
        await self._write(self._mode_pin, level)
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if self.is_on is False:
            await self._write(self._power_pin, 1)
        if preset_mode.casefold() == PRESET_AUTO:
            await self._engage_auto()
            return
        # Any other preset exits auto.
        self._auto_engaged = False
        if preset_mode == PRESET_ECO:
            await self._write(self._mode_pin, MODE_ECO)
        elif preset_mode == PRESET_SLEEP_WHISPER:
            await self._write(self._mode_pin, MODE_SLEEP)
            if self._submode_pin:
                await self._write(self._submode_pin, SLEEP_WHISPER)
        elif preset_mode == PRESET_SLEEP_WHITE_NOISE:
            await self._write(self._mode_pin, MODE_SLEEP)
            if self._submode_pin:
                await self._write(self._submode_pin, SLEEP_WHITE_NOISE)
        await self.coordinator.async_request_refresh()

    async def _engage_auto(self) -> None:
        """Enter the virtual auto preset and set the initial speed from AQI."""
        self._auto_engaged = True
        # Seed hysteresis from the current numbered speed, if V3 holds one.
        mode = self._mode()
        self._auto_speed = mode if mode and 1 <= mode <= self._speed_count else None
        aqi = self._current_aqi()
        if aqi is not None:
            target = auto_target_speed(
                aqi,
                self._auto_thresholds,
                self._speed_count,
                self._auto_speed,
                self._auto_hysteresis,
                min_level=self._auto_min_level,
            )
            self._auto_speed = target
            await self._write(self._mode_pin, target)
        await self.coordinator.async_request_refresh()
