"""End-to-end tests for the Windmill Air Purifier integration (mocked cloud)."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.windmill_air.const import DOMAIN

BASE = "https://dashboard.windmillair.com/external/api"
TOKEN = "test-token-123"

# v0 power, v1 numeric AQI, v3 mode (speed 2 of 4), v4 sleep sub-mode,
# v5 LED fade, v6 beep, v11 child lock, v16 AQI category (getAll returns the
# numeric code; the label comes from an individual get), plus unmapped v7.
PINS = {
    "v0": 1,
    "v1": 7,
    "v3": 2,
    "v4": 1,
    "v5": 1,
    "v6": 0,
    "v7": 71,
    "v11": 0,
    "v16": 1,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components in tests."""
    return


def mock_cloud(aioclient_mock, pins=PINS, online=True, label="Good"):
    aioclient_mock.get(f"{BASE}/isHardwareConnected", text="true" if online else "false")
    aioclient_mock.get(f"{BASE}/getAll", json=pins)
    # Individual get returns enum labels (e.g. the AQI category) and is the
    # fallback for pins missing from getAll.
    aioclient_mock.get(f"{BASE}/get", text=label)
    aioclient_mock.get(f"{BASE}/update", text="")


async def test_config_flow_creates_entry(hass: HomeAssistant, aioclient_mock) -> None:
    mock_cloud(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": TOKEN}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # Model defaults to the larger unit (WAP1M1, the originally-confirmed one).
    assert result["data"] == {"token": TOKEN, "model": "wap1m1"}
    assert result["title"] == "Windmill Air Purifier Max"


async def test_config_flow_selects_smaller_model(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_cloud(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": TOKEN, "model": "sap1v1"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"token": TOKEN, "model": "sap1v1"}
    # Retail name (matches the box); the model id disambiguates it from the
    # app's "Air Purifier" (which is the larger unit).
    assert result["title"] == "Windmill Air Purifier"


async def test_device_registry_shows_model(
    hass: HomeAssistant, aioclient_mock
) -> None:
    from homeassistant.helpers import device_registry as dr

    entry = await _setup_entry(
        hass, aioclient_mock, data={"token": TOKEN, "model": "sap1v1"}
    )
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, entry.entry_id)}
    )
    assert device is not None
    assert device.manufacturer == "Windmill"
    assert device.model == "Air Purifier"
    assert device.model_id == "SAP1V1"


async def test_config_flow_bad_token(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(
        f"{BASE}/isHardwareConnected", status=400, text="Invalid token."
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"token": "bad"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def _setup_entry(hass, aioclient_mock, options=None, data=None) -> MockConfigEntry:
    mock_cloud(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=data or {"token": TOKEN},
        options=options or {},
        title="Windmill",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _last_updates(aioclient_mock):
    return [
        str(c[1].query_string)
        for c in aioclient_mock.mock_calls
        if "update" in str(c[1])
    ]


async def test_entities_created(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_entry(hass, aioclient_mock)

    fan = hass.states.get("fan.windmill")
    assert fan is not None
    assert fan.state == "on"  # v0 == 1
    assert fan.attributes["percentage"] == 50  # v3 == 2 of 4 speeds
    assert fan.attributes["preset_modes"] == [
        "auto",  # first, so Apple Home folds it into the Auto/Manual toggle
        "Eco",
        "Sleep: Whisper",
        "Sleep: White noise",
    ]
    assert fan.attributes["preset_mode"] is None  # numbered speed, not a preset

    # The auto-preset floor, a RestoreNumber at its default
    assert hass.states.get("number.windmill_auto_minimum_speed").state == "1"

    # Switches from the default pin mapping
    assert hass.states.get("switch.windmill_child_lock").state == "off"  # v11 == 0
    assert hass.states.get("switch.windmill_display_auto_dim").state == "on"  # v5 == 1
    assert hass.states.get("switch.windmill_beep").state == "off"  # v6 == 0

    # AQI defaults to v1; other unmapped pins become diagnostic sensors
    # (v7 here), while mapped pins (v1, v3, v16, ...) do not.
    assert hass.states.get("sensor.windmill_air_quality_index").state == "7"  # v1
    # AQI category (v16) shows the label from the individual get, not the code
    assert hass.states.get("sensor.windmill_air_quality").state == "Good"
    assert hass.states.get("sensor.windmill_pin_v7").state == "71"
    assert hass.states.get("sensor.windmill_pin_v3") is None
    assert hass.states.get("sensor.windmill_pin_v1") is None
    assert hass.states.get("sensor.windmill_pin_v16") is None


async def test_speed_slider_writes_mode_pin(
    hass: HomeAssistant, aioclient_mock
) -> None:
    await _setup_entry(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": 4})
    await hass.services.async_call(
        "fan",
        "set_percentage",
        {"entity_id": "fan.windmill", "percentage": 100},
        blocking=True,
    )
    assert any("v3=4" in q for q in _last_updates(aioclient_mock))
    assert hass.states.get("fan.windmill").attributes["percentage"] == 100


async def test_eco_and_sleep_presets(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_entry(hass, aioclient_mock)

    # Eco -> mode pin 5
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": 5})
    await hass.services.async_call(
        "fan",
        "set_preset_mode",
        {"entity_id": "fan.windmill", "preset_mode": "Eco"},
        blocking=True,
    )
    assert any("v3=5" in q for q in _last_updates(aioclient_mock))
    assert hass.states.get("fan.windmill").attributes["preset_mode"] == "Eco"

    # Sleep: White noise -> mode pin 6 and sub-mode pin 2
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": 6, "v4": 2})
    await hass.services.async_call(
        "fan",
        "set_preset_mode",
        {"entity_id": "fan.windmill", "preset_mode": "Sleep: White noise"},
        blocking=True,
    )
    updates = _last_updates(aioclient_mock)
    assert any("v3=6" in q for q in updates)
    assert any("v4=2" in q for q in updates)
    fan = hass.states.get("fan.windmill")
    assert fan.attributes["preset_mode"] == "Sleep: White noise"
    assert fan.attributes["percentage"] is None  # a preset, not a speed


async def _refresh_category(hass, aioclient_mock, coordinator, category, **pins):
    """Re-poll the (mocked) cloud with an AQI category (V16) and pin overrides.

    Uses async_refresh (not async_request_refresh, which is debounced) so the
    poll — and the auto driver's _handle_coordinator_update — run immediately.
    """
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, **pins}, label=category)
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def _engage_auto(hass, aioclient_mock, entry, category, seed_speed):
    """Load an AQI category + seed speed, then engage auto; return the coordinator."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    await _refresh_category(
        hass, aioclient_mock, coordinator, category, v3=seed_speed
    )
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": seed_speed}, label=category)
    await hass.services.async_call(
        "fan",
        "set_preset_mode",
        {"entity_id": "fan.windmill", "preset_mode": "auto"},
        blocking=True,
    )
    return coordinator


async def test_auto_preset_sets_speed_from_category(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await _setup_entry(hass, aioclient_mock)
    # "Bad" (Windmill 101-150) maps to speed 3; seed a manual speed 1 so the
    # auto write is clearly the category-driven choice, not a no-op.
    await _engage_auto(hass, aioclient_mock, entry, category="Bad", seed_speed=1)

    assert any("v3=3" in q for q in _last_updates(aioclient_mock))
    fan = hass.states.get("fan.windmill")
    assert fan.attributes["preset_mode"] == "auto"
    assert fan.state == "on"


async def test_auto_follows_category_across_a_poll(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await _setup_entry(hass, aioclient_mock)
    coordinator = await _engage_auto(
        hass, aioclient_mock, entry, category="Bad", seed_speed=1
    )  # -> speed 3

    # Air quality worsens to "Unhealthy" (speed 4). The device still reports the
    # old speed 3, so the auto driver must write the new speed on this update.
    await _refresh_category(
        hass, aioclient_mock, coordinator, "Unhealthy", v3=3
    )
    assert any("v3=4" in q for q in _last_updates(aioclient_mock))
    assert hass.states.get("fan.windmill").attributes["preset_mode"] == "auto"


async def _set_min_level(hass, value):
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.windmill_auto_minimum_speed", "value": value},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_auto_min_level_floors_speed(
    hass: HomeAssistant, aioclient_mock
) -> None:
    # "Good" maps to speed 1, but a floor of 2 must win: engaging auto from a
    # seeded speed 1 writes speed 2 and never writes speed 1.
    entry = await _setup_entry(hass, aioclient_mock)
    await _set_min_level(hass, 2)
    await _engage_auto(hass, aioclient_mock, entry, category="Good", seed_speed=1)

    assert any("v3=2" in q for q in _last_updates(aioclient_mock))
    assert not any("v3=1" in q for q in _last_updates(aioclient_mock))
    assert hass.states.get("fan.windmill").attributes["preset_mode"] == "auto"


async def test_auto_min_level_change_applies_while_engaged(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await _setup_entry(hass, aioclient_mock)
    # Good air, seed 2: auto steps down and drives speed 1.
    await _engage_auto(hass, aioclient_mock, entry, category="Good", seed_speed=2)
    assert any("v3=1" in q for q in _last_updates(aioclient_mock))

    # Raising the floor while engaged re-drives the speed immediately (via the
    # coordinator's listeners) — no poll happens between set_value and here.
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": 1}, label="Good")
    await _set_min_level(hass, 3)

    assert any("v3=3" in q for q in _last_updates(aioclient_mock))
    assert hass.states.get("fan.windmill").attributes["preset_mode"] == "auto"
    assert hass.states.get("number.windmill_auto_minimum_speed").state == "3"


async def test_auto_min_level_restored_after_restart(
    hass: HomeAssistant, aioclient_mock
) -> None:
    from homeassistant.core import State
    from pytest_homeassistant_custom_component.common import (
        mock_restore_cache_with_extra_data,
    )

    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State("number.windmill_auto_minimum_speed", "3"),
                {
                    "native_max_value": 4.0,
                    "native_min_value": 1.0,
                    "native_step": 1.0,
                    "native_unit_of_measurement": None,
                    "native_value": 3.0,
                },
            )
        ],
    )
    entry = await _setup_entry(hass, aioclient_mock)
    assert hass.states.get("number.windmill_auto_minimum_speed").state == "3"

    # The restored floor drives the very first auto write.
    await _engage_auto(hass, aioclient_mock, entry, category="Good", seed_speed=1)
    assert any("v3=3" in q for q in _last_updates(aioclient_mock))


async def test_manual_speed_exits_auto(
    hass: HomeAssistant, aioclient_mock
) -> None:
    entry = await _setup_entry(hass, aioclient_mock)
    await _engage_auto(hass, aioclient_mock, entry, category="Bad", seed_speed=1)

    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": 4}, label="Bad")
    await hass.services.async_call(
        "fan",
        "set_percentage",
        {"entity_id": "fan.windmill", "percentage": 100},
        blocking=True,
    )
    fan = hass.states.get("fan.windmill")
    assert fan.attributes["preset_mode"] is None  # auto disengaged
    assert fan.attributes["percentage"] == 100


async def test_eco_exits_auto(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup_entry(hass, aioclient_mock)
    await _engage_auto(hass, aioclient_mock, entry, category="Bad", seed_speed=1)

    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": 5}, label="Bad")
    await hass.services.async_call(
        "fan",
        "set_preset_mode",
        {"entity_id": "fan.windmill", "preset_mode": "Eco"},
        blocking=True,
    )
    assert hass.states.get("fan.windmill").attributes["preset_mode"] == "Eco"


async def test_speed_count_clamped_below_eco(
    hass: HomeAssistant, aioclient_mock
) -> None:
    # A speed_count of 5 would put the top of the slider on the Eco enum value.
    # It must be clamped so 100% still writes a real fan speed (4), not Eco (5).
    await _setup_entry(hass, aioclient_mock, options={"speed_count": 5})
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v3": 4})
    await hass.services.async_call(
        "fan",
        "set_percentage",
        {"entity_id": "fan.windmill", "percentage": 100},
        blocking=True,
    )
    assert any("v3=4" in q for q in _last_updates(aioclient_mock))
    assert not any("v3=5" in q for q in _last_updates(aioclient_mock))
    assert hass.states.get("fan.windmill").attributes["percentage"] == 100


async def test_switch_toggle_writes_pin(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_entry(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock, pins={**PINS, "v11": 1})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.windmill_child_lock"}, blocking=True
    )
    assert any("v11=1" in q for q in _last_updates(aioclient_mock))
    assert hass.states.get("switch.windmill_child_lock").state == "on"


async def test_aqi_pin_hidden_from_getall_is_fetched_individually(
    hass: HomeAssistant, aioclient_mock
) -> None:
    # v9 is NOT in the getAll blob, but the device returns it via get?v9 —
    # the coordinator must fall back to an individual fetch for mapped pins.
    aioclient_mock.get(f"{BASE}/isHardwareConnected", text="true")
    aioclient_mock.get(f"{BASE}/getAll", json=PINS)  # no v9
    aioclient_mock.get(f"{BASE}/get", text="[12]")  # individual v9 fetch
    aioclient_mock.get(f"{BASE}/update", text="")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"token": TOKEN},
        options={"aqi_pin": "v9"},
        title="Windmill",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    aqi = hass.states.get("sensor.windmill_air_quality_index")
    assert aqi is not None
    assert aqi.state == "12"
    assert hass.states.get("sensor.windmill_pin_v9") is None


async def test_device_offline_marks_unavailable(
    hass: HomeAssistant, aioclient_mock
) -> None:
    mock_cloud(aioclient_mock, online=False)
    entry = MockConfigEntry(domain=DOMAIN, data={"token": TOKEN}, title="Windmill")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("fan.windmill").state == "unavailable"
