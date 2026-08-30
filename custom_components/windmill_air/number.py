"""Number entities (auto-preset tuning) for the Windmill purifier."""

from __future__ import annotations

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_AQI_CATEGORY_PIN,
    CONF_AUTO_PRESET_ENABLED,
    CONF_SPEED_COUNT,
    DEFAULT_AUTO_PRESET_ENABLED,
    DOMAIN,
    MODE_ECO,
)
from .coordinator import WindmillCoordinator
from .entity import WindmillEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WindmillCoordinator = hass.data[DOMAIN][entry.entry_id]
    options = entry.options
    model = coordinator.model
    # Only useful when the fan offers the auto preset (same condition fan.py
    # uses to include "auto" in preset_modes).
    auto_enabled = bool(
        options.get(CONF_AUTO_PRESET_ENABLED, DEFAULT_AUTO_PRESET_ENABLED)
    )
    category_pin = options.get(CONF_AQI_CATEGORY_PIN, model.aqi_category_pin)
    if not (auto_enabled and category_pin):
        return
    # Same clamp as the fan's speed slider: never past Eco's enum value.
    speed_count = max(
        1, min(int(options.get(CONF_SPEED_COUNT, model.speed_count)), MODE_ECO - 1)
    )
    async_add_entities([WindmillAutoMinLevel(coordinator, speed_count)])


class WindmillAutoMinLevel(WindmillEntity, RestoreNumber):
    """Floor for the emulated auto preset: auto never picks a lower speed.

    The value lives on the coordinator (not in config-entry options: writing
    options reloads the entry, which would drop the in-memory auto-engaged
    state) and is persisted across restarts by RestoreNumber.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:fan-chevron-up"
    _attr_mode = NumberMode.SLIDER
    _attr_name = "Auto minimum speed"
    _attr_native_min_value = 1
    _attr_native_step = 1

    def __init__(self, coordinator: WindmillCoordinator, speed_count: int) -> None:
        super().__init__(coordinator, "auto_min_level")
        self._attr_native_max_value = speed_count

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        data = await self.async_get_last_number_data()
        if data is not None and data.native_value is not None:
            self.coordinator.auto_min_level = self._clamp(data.native_value)

    def _clamp(self, value: float) -> int:
        return max(1, min(int(value), int(self._attr_native_max_value)))

    @property
    def native_value(self) -> int:
        # int (not float) so the state renders as "2", matching the step.
        return self.coordinator.auto_min_level

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.auto_min_level = self._clamp(value)
        # Notifying listeners updates this entity's state AND makes an
        # auto-engaged fan re-derive its speed immediately (fan.py
        # _handle_coordinator_update -> _apply_auto_speed).
        self.coordinator.async_update_listeners()
