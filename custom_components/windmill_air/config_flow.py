"""Config flow for the Windmill Air Purifier integration."""

from __future__ import annotations

import hashlib
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import WindmillAirApi, WindmillApiError, WindmillAuthError
from .const import (
    CONF_AQI_CATEGORY_PIN,
    CONF_AQI_PIN,
    CONF_AUTO_HYSTERESIS,
    CONF_AUTO_PRESET_ENABLED,
    CONF_AUTO_THRESHOLD_1,
    CONF_AUTO_THRESHOLD_2,
    CONF_AUTO_THRESHOLD_3,
    CONF_BEEP_PIN,
    CONF_CHILD_LOCK_PIN,
    CONF_LED_FADE_PIN,
    CONF_MODE_PIN,
    CONF_MODEL,
    CONF_PM25_PIN,
    CONF_POWER_PIN,
    CONF_SLEEP_SUBMODE_PIN,
    CONF_SPEED_COUNT,
    CONF_TOKEN,
    CONF_UPDATE_INTERVAL,
    DEFAULT_AUTO_HYSTERESIS,
    DEFAULT_AUTO_PRESET_ENABLED,
    DEFAULT_AUTO_THRESHOLD_1,
    DEFAULT_AUTO_THRESHOLD_2,
    DEFAULT_AUTO_THRESHOLD_3,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MODE_ECO,
)
from .models import DEFAULT_MODEL, MODELS, get_model

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TOKEN): str,
        vol.Required(CONF_MODEL, default=DEFAULT_MODEL): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=model.key, label=model.picker_label)
                    for model in MODELS.values()
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


async def _validate_token(hass, token: str) -> dict[str, Any]:
    """Check the token against the Windmill cloud; return the pin snapshot."""
    api = WindmillAirApi(async_get_clientsession(hass), token)
    await api.is_connected()  # raises WindmillAuthError on a bad token
    return await api.get_all()


class WindmillConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial token setup and reauth."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            try:
                await _validate_token(self.hass, token)
            except WindmillAuthError:
                errors["base"] = "invalid_auth"
            except WindmillApiError:
                errors["base"] = "cannot_connect"
            else:
                unique_id = hashlib.sha256(token.encode()).hexdigest()[:12]
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                model = get_model(user_input.get(CONF_MODEL))
                return self.async_create_entry(
                    title=f"Windmill {model.name}",
                    data={CONF_TOKEN: token, CONF_MODEL: model.key},
                )
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()
            try:
                await _validate_token(self.hass, token)
            except WindmillAuthError:
                errors["base"] = "invalid_auth"
            except WindmillApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data={CONF_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> WindmillOptionsFlow:
        return WindmillOptionsFlow()


class WindmillOptionsFlow(OptionsFlow):
    """Let the user map Blynk datastreams (pins) to entities."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            cleaned = {
                key: value.strip().lower() if isinstance(value, str) else value
                for key, value in user_input.items()
            }
            return self.async_create_entry(title="", data=cleaned)

        options = self.config_entry.options
        model = get_model(self.config_entry.data.get(CONF_MODEL))

        # Show a live snapshot of all datastreams to make mapping easier.
        snapshot = "unavailable"
        try:
            pins = await _validate_token(
                self.hass, self.config_entry.data[CONF_TOKEN]
            )
            snapshot = (
                ", ".join(f"{k.upper()}={v}" for k, v in sorted(pins.items()))
                or "no datastreams reported"
            )
        except WindmillApiError:
            pass

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_POWER_PIN,
                    default=options.get(CONF_POWER_PIN, model.power_pin),
                ): str,
                vol.Required(
                    CONF_MODE_PIN,
                    default=options.get(CONF_MODE_PIN, model.mode_pin),
                ): str,
                # Cap at MODE_ECO - 1: values >= MODE_ECO (5) / MODE_SLEEP (6)
                # would collide with the Eco/Sleep enum on the mode pin, so the
                # top speed (100%) must never reach them.
                vol.Required(
                    CONF_SPEED_COUNT,
                    default=min(
                        options.get(CONF_SPEED_COUNT, model.speed_count),
                        MODE_ECO - 1,
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MODE_ECO - 1)),
                vol.Optional(
                    CONF_SLEEP_SUBMODE_PIN,
                    default=options.get(
                        CONF_SLEEP_SUBMODE_PIN, model.sleep_submode_pin
                    ),
                ): str,
                vol.Optional(
                    CONF_AQI_PIN, default=options.get(CONF_AQI_PIN, model.aqi_pin)
                ): str,
                vol.Optional(
                    CONF_AQI_CATEGORY_PIN,
                    default=options.get(
                        CONF_AQI_CATEGORY_PIN, model.aqi_category_pin
                    ),
                ): str,
                vol.Optional(
                    CONF_PM25_PIN, default=options.get(CONF_PM25_PIN, "")
                ): str,
                vol.Optional(
                    CONF_CHILD_LOCK_PIN,
                    default=options.get(CONF_CHILD_LOCK_PIN, model.child_lock_pin),
                ): str,
                vol.Optional(
                    CONF_LED_FADE_PIN,
                    default=options.get(CONF_LED_FADE_PIN, model.led_fade_pin),
                ): str,
                vol.Optional(
                    CONF_BEEP_PIN,
                    default=options.get(CONF_BEEP_PIN, model.beep_pin),
                ): str,
                # --- "Auto" preset (AQI-driven, emulated in software) ---
                vol.Required(
                    CONF_AUTO_PRESET_ENABLED,
                    default=options.get(
                        CONF_AUTO_PRESET_ENABLED, DEFAULT_AUTO_PRESET_ENABLED
                    ),
                ): bool,
                vol.Required(
                    CONF_AUTO_THRESHOLD_1,
                    default=options.get(
                        CONF_AUTO_THRESHOLD_1, DEFAULT_AUTO_THRESHOLD_1
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
                vol.Required(
                    CONF_AUTO_THRESHOLD_2,
                    default=options.get(
                        CONF_AUTO_THRESHOLD_2, DEFAULT_AUTO_THRESHOLD_2
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
                vol.Required(
                    CONF_AUTO_THRESHOLD_3,
                    default=options.get(
                        CONF_AUTO_THRESHOLD_3, DEFAULT_AUTO_THRESHOLD_3
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=500)),
                vol.Required(
                    CONF_AUTO_HYSTERESIS,
                    default=options.get(
                        CONF_AUTO_HYSTERESIS, DEFAULT_AUTO_HYSTERESIS
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=options.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=600)),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"snapshot": snapshot},
        )
