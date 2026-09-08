# GenlcUI

A Linux desktop controller for Genelec SAM monitors, driving the GLM network
adapter directly over USB HID. Built for KDE Plasma on Wayland.

Genelec ships GLM for Windows and macOS but not Linux. This fills that gap for
day-to-day control -- levels, presets, wake/sleep, live status. It is **not** a
calibration tool and never writes to speaker flash, so a calibration made with
GLM5 stays exactly as you left it.

## Status

Core protocol layer complete and tested against real hardware (Genelec 7350A +
2x 8330A, GLM adapter firmware 1.3.2.5053). UI in progress.

## Design: the knob is master

GenlcUI follows GLM's own model rather than inventing one:

- **No software fader and no typed levels.** A mouse slip is a hearing hazard.
- **The hardware volume knob is the master.** The UI displays its position.
- **Four level presets**, recalled with a click, deselecting the moment you
  touch the knob.
- **Presets are captured from the knob**, never typed -- so a stored level is
  by construction one you have just listened to.
- **A configurable ceiling** (default -30 dBFS) clamps programmatic writes.

See [docs/DESIGN.md](docs/DESIGN.md) for the reasoning.

## Install

Requires access to the GLM adapter's HID device, which is root-only by default:

    sudo install -m 0644 packaging/udev/70-genelec-glm.rules /etc/udev/rules.d/
    sudo udevadm control --reload-rules && sudo udevadm trigger

Then:

    uv venv && uv pip install -e .
    ./packaging/install-icons.sh      # icon + desktop entry
    genlcui

## Protocol

The GLM protocol is proprietary and undocumented. [docs/PROTOCOL.md](docs/PROTOCOL.md)
records what has been established by live capture, including several places
where the earlier [genlc](https://github.com/markbergsma/genlc) project's
model is wrong in ways that break working systems -- most notably that its
`bypass(led_color=...)` API does not set an LED colour and will disable your
volume control.

## Relationship to genlc

This project began from [markbergsma/genlc](https://github.com/markbergsma/genlc)
(GPLv3), vendored under `genlc/` for reference and attribution. GenlcUI's own
protocol implementation in `genlcui/core/` is a rewrite: upstream's poll parser
uses fixed offsets where the wire format is tag-value encoded, and it does not
read the adapter's volume field at all.

GenlcUI is GPLv3 in consequence.

## Development

    .venv/bin/python -m pytest        # 66 tests, no hardware needed

Diagnostic scripts under `scripts/` talk to real hardware; each says at the
top whether it writes anything.
