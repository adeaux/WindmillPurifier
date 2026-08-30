# Windmill Air Purifier for Home Assistant

[![Validate](https://github.com/adeaux/WindmillPurifier/actions/workflows/validate.yml/badge.svg)](https://github.com/adeaux/WindmillPurifier/actions/workflows/validate.yml)
[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

A custom [Home Assistant](https://www.home-assistant.io/) integration that controls the
[Windmill Air Purifier](https://windmillair.com/products/the-windmill-air-purifier)
— both the **Air Purifier Max** (`WAP1M1`) and the smaller **Air Purifier**
(`SAP1V1`) — through Windmill's cloud, a white-labeled [Blynk](https://blynk.io)
server at `dashboard.windmillair.com`.

There's a community integration for the Windmill **AC**, but nothing for the
**purifier** — this fills that gap.

> ⚠️ **Unofficial.** Not associated with, maintained, supported, or endorsed by
> Windmill. Their cloud can change and break this at any time.

## Features

- **Fan** — power, 4 fan speeds, and presets: **auto** (air-quality-driven), **Eco**,
  **Sleep: Whisper**, **Sleep: White noise**
- **Auto preset** — a mode the integration emulates (the device has no hardware auto): while
  active it sets the fan speed from the air-quality category (Good/Moderate/Bad/Unhealthy).
  Named exactly `auto` so Home Assistant wires it to Apple Home's **Auto/Manual** toggle.
- **Air quality** — a Good/Moderate/Bad/Unhealthy **category** sensor (the device's own
  PM2.5-based signal, and the source the auto preset follows), plus a numeric **AQI** sensor
  (V1) that reads a live 0–500 index matching the number shown in the Windmill app.
- **Switches** — child lock, display auto-dim, beep (audible feedback)
- **Diagnostic sensors** for every unmapped datastream, to help map other units
- UI config flow (just paste your device Auth Token) with reauth support
- All pins remappable via the options flow, for units that differ

## Supported devices

Windmill sells two purifiers, and you pick yours when adding the integration.

⚠️ **Windmill's names are inconsistent across surfaces**, so identify your unit
by its **model number** (on the rating label / box), not its name:

| Model number | Size | Retail name (box, windmillair.com) | App / dashboard name |
|--------------|------|------------------------------------|----------------------|
| `WAP1M1` | larger | Air Purifier **Max** | Air Purifier |
| `SAP1V1` | smaller | Air Purifier | Air Purifier **Mini** |

Note the trap: "Windmill Air Purifier" is the **larger** unit in the app but the
**smaller** unit at retail. The setup picker shows both names plus the model
number so you can't pick wrong. `WAP1M1` is what this integration was developed
and confirmed against; `SAP1V1` defaults to that same layout until verified on
real hardware (see below).

The chosen model sets the default pin layout / fan-speed count and the model
name (and number) shown for the device in Home Assistant. Every pin is still
remappable afterwards, and unmapped pins show up as diagnostic sensors to help
you adjust — so an unconfirmed unit or a firmware variant can always be tuned by
hand. Model definitions live in
[`custom_components/windmill_air/models.py`](custom_components/windmill_air/models.py);
add a new entry there to support another unit.

> **Note on the smaller Air Purifier (`SAP1V1`):** its pin layout is currently
> assumed identical to the Max and has not yet been confirmed on hardware. If any
> control misbehaves, map it out with `scripts/discover_pins.py` (below) and
> either fix it in the options flow or update `MODEL_SAP1V1` in `models.py`.

## Installation

### HACS (custom repository)

1. HACS → three-dot menu → **Custom repositories** → add
   `https://github.com/adeaux/WindmillPurifier` with category **Integration**.
2. Install **Windmill Air Purifier**, then **restart Home Assistant**.

### Manual

Copy `custom_components/windmill_air/` into your HA `config/custom_components/`
folder and restart.

## Setup

1. Get your device **Auth Token**: log in at
   [dashboard.windmillair.com](https://dashboard.windmillair.com) with your
   Windmill app account → **Devices** tab → select your purifier → copy the Auth Token.
2. **Settings → Devices & Services → Add Integration → Windmill Air Purifier**,
   pick your **model** (Air Purifier Max / Air Purifier), and paste the token.

The model you choose seeds the correct defaults, so no manual mapping is usually
needed. Adding both units? Repeat the steps with each device's own token — every
config entry keeps its own model and pin mapping.

## Entities

| Entity | Source | Notes |
|--------|--------|-------|
| `fan.windmill…` | V0 power, V3 mode, V16 category | 4-speed slider + auto / Eco / Sleep presets |
| `sensor.…air_quality_index` | V1 | numeric AQI 0–500 (matches the Windmill app) |
| `sensor.…air_quality` | V16 | category: Good / Moderate / … (drives the auto preset) |
| `number.…auto_minimum_speed` | — | floor for the auto preset (see below) |
| `switch.…child_lock` | V11 | |
| `switch.…display_auto_dim` | V5 | LED auto-fade after interaction |
| `switch.…beep` | V6 | audible feedback |
| `sensor.…pin_v#` | unmapped pins | diagnostic, for discovery |

## How it works

Windmill devices are Blynk devices: state lives in numbered virtual datastreams
("pins"), read/written over Blynk's token-authenticated device HTTPS API. The
integration polls `getAll` and writes with `update`.

Two Blynk quirks are handled automatically:

- **`getAll` can omit datastreams** that have no web-dashboard widget. Any pin you
  map that's missing from the bulk response is fetched individually via `get?vN`.
- **`get?vN` returns human labels** for enum pins (e.g. the AQI category), so the
  category pin is always fetched individually to show "Good"/"Moderate" rather
  than a raw code.

## The "auto" preset

The Windmill has **no hardware auto mode** — its mode pin (V3) only holds the numbered
speeds and the Eco / Sleep values. This integration emulates one in software:

- Selecting the **auto** preset marks the fan as "auto-engaged" (tracked inside the
  integration, not on any pin) and powers the fan on.
- On every poll, while engaged, the integration reads the **air-quality category** (V16 — the
  device's own Good / Moderate / Bad / Unhealthy status) and writes the matching numbered
  speed to V3 — worse air quality → higher speed. The speed slider keeps showing the current
  auto-selected speed.
- Setting a **manual speed**, or picking **Eco** / **Sleep**, or turning the fan **off**,
  exits auto.

The preset is named exactly `auto` so that, when the fan is exposed to Apple Home as an
`air_purifier` accessory, Home's **Auto/Manual** toggle drives it.

### Category → speed mapping

Auto follows the device's air-quality category (the same status behind the purifier's
indicator light, which is PM2.5-based). The default mapping matches the 4-speed unit:

| Category (V16) | AQI band | Auto speed |
|----------------|----------|-----------|
| Good | 0–50 | 1 |
| Moderate | 51–100 | 2 |
| Bad | 101–150 | 3 |
| Unhealthy | 151+ | 4 |

Matching is case-insensitive and by keyword, and any unrecognized status simply holds the
current speed. (Other AQI wordings — "Unhealthy for Sensitive Groups", "Very Unhealthy",
"Hazardous" — are also understood, for units that use them.)

The category is converted to a representative AQI and passed through three tunable
**thresholds** (defaults 50 / 100 / 150, on the 0–500 scale) that decide which status bumps
which speed; a **hysteresis** dead-band (default 10) eases the speed back down only after the
air quality improves past a threshold. Adjust both in the **Configure** dialog — the defaults
give the table above and rarely need changing. The preset can be turned off with the
**Enable the "auto" preset** option (it also hides if no category pin is mapped). Auto state
is in-memory, so it resets to manual after a Home Assistant restart or an options change —
just re-select Auto.

### Minimum auto speed

The **Auto minimum speed** number entity on the device (default 1) is a floor auto never
drops below — set it to 2 to keep more air moving even when the air is Good. It's a live
entity rather than a Configure option so it can be changed from dashboards, scripts, and
automations (`number.set_value`); a change applies immediately, even while auto is engaged,
and the value survives restarts. It doesn't appear in Apple Home (HomeKit's air-purifier
accessory has no slot for it), but you can get indirect Home-app control by exposing an
`input_boolean` to HomeKit and letting an automation call `number.set_value` when it flips.

## Air quality readout (PM2.5) — status

Apple Home's air-quality tile wants a real **PM2.5 density in µg/m³**. V1 is a live **AQI
*index*** (0–500, confirmed to match the number in the Windmill app), but an index is a
different unit than µg/m³, so it can't drive that tile. A smoke test on the tested unit found
**no datastream that reports raw µg/m³ PM2.5** — only the AQI index (V1) and the
Good/Moderate/Bad/Unhealthy category (V16) respond to air quality. The integration keeps a
ready PM2.5 sensor scaffold anyway: if a unit ever exposes such a pin (scan for it with
`scripts/discover_pins.py --scan`/`--watch` and look for small numbers that track air quality),
map it to **PM2.5 sensor pin** in the options to expose `sensor.…pm2_5` — which can then be
linked in the HomeKit bridge. The auto preset is unaffected either way: it follows the V16
category.

## Configuration & remapping

Open the integration's **Configure** dialog to remap any pin (blank disables that
entity), tune the auto preset, or change the polling interval. The dialog shows a live
snapshot of all current pin values. Confirmed default mapping:

| Pin | Function |
|-----|----------|
| V0 | Power |
| V1 | AQI (numeric 0–500, matches the app) |
| V3 | Mode: 1–4 speeds, 5 = Eco, 6 = Sleep (auto writes a numbered speed here) |
| V4 | Sleep sub-mode: 1 = Whisper, 2 = White noise |
| V5 | Display auto-dim |
| V6 | Beep |
| V11 | Child lock |
| V16 | AQI category (Good / Moderate / Bad / Unhealthy — drives the auto preset) |

### Discovering pins on a different unit

`scripts/discover_pins.py` (standard library only):

```bash
python3 scripts/discover_pins.py YOUR_TOKEN --watch    # highlight pins that change live
python3 scripts/discover_pins.py YOUR_TOKEN --scan     # probe v0..v120, flag getAll-hidden pins
python3 scripts/discover_pins.py YOUR_TOKEN --set v3=5  # test a write (Eco)
```

Change one setting at a time in the Windmill app and note which pin flips.

## Development

```bash
pip install pytest-homeassistant-custom-component
pytest
```

The suite runs the integration end-to-end against a mocked cloud (config flow,
entities, fan/preset/switch writes, the category-driven auto preset, the
getAll-omission fallback, the category label override, offline handling), plus
pure unit tests for the category → AQI → speed mapping and hysteresis.

### Testing this build against your real device, in parallel

To try an in-development version on your actual purifier without disturbing your stable
install, generate a second copy under a different domain:

```bash
python3 scripts/make_dev_copy.py
```

This writes `custom_components/windmill_air_dev/` (gitignored). Restart Home Assistant and
add **Windmill Air Purifier (dev)** with the *same* Auth Token — it installs as a separate
integration alongside the stable one, pointed at the same device. Observe/compare freely;
just avoid actively driving controls from both at once (both write the mode pin). Delete the
folder and restart when done.

## Credits

- API pattern reverse-engineered by the community for the Windmill AC:
  [bzellman/WindmillAC](https://github.com/bzellman/WindmillAC) and
  [johnanthonyeletto/homebridge-windmill-ac](https://github.com/johnanthonyeletto/homebridge-windmill-ac)
- [Blynk device HTTPS API docs](https://docs.blynk.io/en/blynk.cloud/device-https-api)

## License

[MIT](LICENSE)
