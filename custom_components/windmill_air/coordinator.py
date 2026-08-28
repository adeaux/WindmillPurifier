"""Data update coordinator for the Windmill Air Purifier."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WindmillAirApi, WindmillApiError, WindmillAuthError
from .const import (
    CONF_AQI_CATEGORY_PIN,
    CONF_MODEL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_AQI_CATEGORY_PIN,
    DEFAULT_AUTO_MIN_LEVEL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOGGER,
)
from .models import WindmillModel, get_model


@dataclass
class WindmillData:
    """Snapshot of the device state."""

    online: bool
    pins: dict[str, Any]


class WindmillCoordinator(DataUpdateCoordinator[WindmillData]):
    """Polls all datastream values from the Windmill cloud."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: WindmillAirApi
    ) -> None:
        interval = entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.api = api
        # The selected model supplies default pins / speed count and the label
        # shown for the device (see models.py). Entries predating models fall
        # back to the default model.
        self.model: WindmillModel = get_model(entry.data.get(CONF_MODEL))
        # Floor for the emulated auto preset. Owned (set and restored) by the
        # auto-minimum-speed number entity; read by the fan on every auto step.
        self.auto_min_level: int = DEFAULT_AUTO_MIN_LEVEL

    def _configured_pins(self) -> list[str]:
        """Pin names explicitly mapped in the options (keys ending in _pin)."""
        pins = []
        for key, value in self.config_entry.options.items():
            if key.endswith("_pin") and isinstance(value, str) and value.strip():
                pins.append(value.strip().lower())
        return pins

    def _label_pins(self) -> list[str]:
        """Pins whose text label (via get) is preferred over the getAll number."""
        pin = self.config_entry.options.get(
            CONF_AQI_CATEGORY_PIN, DEFAULT_AQI_CATEGORY_PIN
        )
        return [pin.strip().lower()] if pin else []

    async def _async_update_data(self) -> WindmillData:
        try:
            online = await self.api.is_connected()
            pins = await self.api.get_all()
            # Blynk's getAll can omit datastreams that have no web-dashboard
            # widget (e.g. AQI on some units). Fetch any explicitly mapped pin
            # that's missing from the bulk response individually.
            for pin in self._configured_pins():
                if pin in pins:
                    continue
                try:
                    value = await self.api.get_pin(pin)
                except WindmillApiError:
                    continue
                if value not in ("", None):
                    pins[pin] = value
            # Some pins carry an enum label (Good/Moderate/…) that getAll
            # returns as a bare code; fetch those individually for the label.
            for pin in self._label_pins():
                try:
                    value = await self.api.get_pin(pin)
                except WindmillApiError:
                    continue
                if value not in ("", None):
                    pins[pin] = value
        except WindmillAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except WindmillApiError as err:
            raise UpdateFailed(str(err)) from err
        return WindmillData(online=online, pins=pins)

    def pin_value(self, pin: str | None) -> Any:
        """Return the last known value of a pin, or None."""
        if not pin or self.data is None:
            return None
        return self.data.pins.get(pin.lower())

    def set_pin_optimistic(self, pin: str, value: Any) -> None:
        """Update the local snapshot after a successful write."""
        if self.data is not None:
            self.data.pins[pin.lower()] = value
            self.async_update_listeners()
