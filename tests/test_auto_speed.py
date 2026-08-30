"""Unit tests for the pure AQI -> speed mapping used by the "auto" preset."""

import pytest

from custom_components.windmill_air.fan import auto_target_speed, category_to_aqi

# Default 4-speed device thresholds and dead-band.
THRESHOLDS = [50, 100, 150]
SPEED_COUNT = 4
HYST = 10


@pytest.mark.parametrize(
    ("aqi", "expected"),
    [
        (0, 1),
        (49, 1),
        (50, 2),  # at the boundary -> steps up
        (99, 2),
        (100, 3),
        (149, 3),
        (150, 4),
        (500, 4),  # clamped to speed_count
    ],
)
def test_bands_map_to_speeds(aqi, expected):
    # current=None: first engage, hysteresis does not apply.
    assert auto_target_speed(aqi, THRESHOLDS, SPEED_COUNT, None, HYST) == expected


def test_steps_up_at_threshold_no_dead_band():
    # Rising: step up as soon as the AQI reaches the threshold (100), not 100+hyst.
    assert auto_target_speed(99, THRESHOLDS, SPEED_COUNT, 2, HYST) == 2   # below -> holds
    assert auto_target_speed(100, THRESHOLDS, SPEED_COUNT, 2, HYST) == 3  # at threshold -> steps


def test_hysteresis_holds_stepping_down():
    # Boundary between speed 2 and 3 is 100; need < 90 to step down from 3.
    assert auto_target_speed(95, THRESHOLDS, SPEED_COUNT, 3, HYST) == 3  # holds
    assert auto_target_speed(89, THRESHOLDS, SPEED_COUNT, 3, HYST) == 2  # steps


def test_hysteresis_is_downward_only():
    # At exactly 100 the up-point and the resting band agree (speed 3), but once
    # there it won't drop back to 2 until the AQI falls below 90 -> no flapping.
    assert auto_target_speed(100, THRESHOLDS, SPEED_COUNT, 2, HYST) == 3  # up at 100
    assert auto_target_speed(95, THRESHOLDS, SPEED_COUNT, 3, HYST) == 3   # sticky down
    assert auto_target_speed(90, THRESHOLDS, SPEED_COUNT, 3, HYST) == 3   # still holds
    assert auto_target_speed(89, THRESHOLDS, SPEED_COUNT, 3, HYST) == 2   # releases


def test_large_jump_moves_multiple_speeds():
    # A big AQI spike jumps straight to the top speed once past the dead-band.
    assert auto_target_speed(300, THRESHOLDS, SPEED_COUNT, 1, HYST) == 4


def test_no_thresholds_is_safe():
    assert auto_target_speed(200, [], SPEED_COUNT, 3, HYST) == 1


def test_speed_count_above_thresholds_does_not_index_error():
    # 6 speeds but only 3 thresholds: high seeds must not raise.
    assert auto_target_speed(0, THRESHOLDS, 6, 6, HYST) == 1


@pytest.mark.parametrize(
    ("aqi", "expected"),
    [
        (0, 1),
        (49, 1),
        (50, 2),
        (99, 2),
        (100, 3),
        (149, 3),
        (150, 4),
        (500, 4),
    ],
)
def test_min_level_1_matches_default(aqi, expected):
    # Explicit min_level=1 is byte-for-byte the default behavior.
    assert (
        auto_target_speed(aqi, THRESHOLDS, SPEED_COUNT, None, HYST, min_level=1)
        == expected
    )


def test_min_level_floors_low_aqi():
    # Good air (AQI 25) would pick speed 1; a floor of 2 keeps it at 2.
    assert auto_target_speed(25, THRESHOLDS, SPEED_COUNT, None, HYST, min_level=2) == 2


def test_min_level_no_oscillation_at_floor():
    # Sitting at the floor with low AQI: naive == current, so it just holds.
    assert auto_target_speed(25, THRESHOLDS, SPEED_COUNT, 2, HYST, min_level=2) == 2
    assert auto_target_speed(0, THRESHOLDS, SPEED_COUNT, 2, HYST, min_level=2) == 2


def test_min_level_raises_current_below_floor():
    # Engaging auto while a manual speed 1 is seeded: floor wins immediately.
    assert auto_target_speed(25, THRESHOLDS, SPEED_COUNT, 1, HYST, min_level=2) == 2


def test_min_level_keeps_hysteresis_above_floor():
    # With floor 2, stepping 3 -> 2 still uses the real boundary (100 - hyst)...
    assert auto_target_speed(95, THRESHOLDS, SPEED_COUNT, 3, HYST, min_level=2) == 3
    assert auto_target_speed(89, THRESHOLDS, SPEED_COUNT, 3, HYST, min_level=2) == 2
    # ...and rising is still immediate.
    assert auto_target_speed(100, THRESHOLDS, SPEED_COUNT, 2, HYST, min_level=2) == 3


def test_min_level_clamped_to_speed_count():
    # A floor above the speed count can't push past the top of the slider.
    assert auto_target_speed(0, THRESHOLDS, 2, None, HYST, min_level=4) == 2


def test_min_level_no_thresholds_returns_floor():
    assert auto_target_speed(200, [], SPEED_COUNT, 3, HYST, min_level=3) == 3


@pytest.mark.parametrize(
    ("label", "expected_speed"),
    [
        ("Good", 1),  # -> 25
        ("Moderate", 2),  # -> 75
        ("Bad", 3),  # Windmill 101-150 -> 125
        ("Unhealthy", 4),  # Windmill 151+ -> 175
        ("Very Unhealthy", 4),  # must NOT be caught by the plain "unhealthy" rule
        ("Unhealthy for Sensitive Groups", 3),  # "sensitive" wins -> 125
        ("hazardous", 4),
    ],
)
def test_category_maps_to_speed(label, expected_speed):
    aqi = category_to_aqi(label)
    assert aqi is not None
    assert auto_target_speed(aqi, THRESHOLDS, SPEED_COUNT, None, HYST) == expected_speed


def test_category_unknown_or_blank_is_none():
    assert category_to_aqi("Excellent") is None
    assert category_to_aqi("") is None
    assert category_to_aqi(None) is None
