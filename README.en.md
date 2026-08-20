<div align="center">

# M5Stack StopWatch Simulator

[日本語](README.md) · **English** · [中文](README.zh-CN.md)

The production firmware's own C++ runs on your Mac.<br>
Text is measured with the device's real font metrics, so you can settle screen questions here.

[![CI](https://github.com/ochyai/m5stack-stopwatch-simulator/actions/workflows/ci.yml/badge.svg)](https://github.com/ochyai/m5stack-stopwatch-simulator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-informational.svg)](LICENSE)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)](macos/M5StackSimulator/README.md)

<img src="docs/images/workbench.png" alt="Firmware Workbench: firmware list and build on the left, the live device in the centre, an input and sensor Inspector on the right, an event timeline below" width="900">

</div>

A repository for exploring and developing the M5Stack StopWatch (C152) reproducibly from a Mac. The round AMOLED, touch, two buttons, six-axis IMU, RTC, microphone, speaker, haptics, Wi-Fi / Bluetooth LE, and external I2C are covered by per-feature firmware and one simulator. The default app, **SOKKON / 即今**, turns this round device into a surface that physically holds your current context.

> [!CAUTION]
> On some production runs the rear terminal is silkscreened `BAT`, which is wrong. It is **5V IN** for external power. Do not connect a lithium battery. This is M5Stack's own correction.

## What makes it different from a mock

- **It is not a mock.** What the browser shows is the result of compiling the production `main.cpp` and `board.cpp` with the host C++ compiler and running them. No UI state machine is reimplemented in JavaScript.
- **Text width is measured, not estimated.** `font_metrics.hpp` is generated from the M5GFX package the firmware links, and `sim_text.hpp` ports LovyanGFX's `text_width` and `draw_string` down to the fixed point. `10_sokkon` truncates its context line with `...` until it fits 300 px, and it now truncates at the same character the panel does.
- **One interpreter for draw commands.** Both front ends import `frame-renderer.js`, so a pixel cannot depend on which UI you happen to have open.
- **A touch carries its coordinate.** Pressing anywhere on the glass sends that device pixel into the production `loop()`, which is how you can see that `10_sokkon` ignores everything outside its 145 px focus ring.
- **Sessions replay exactly.** Virtual time is frozen during a replay, so the same script draws the same frames on any machine. That is what makes golden frames possible.

## Run it in 30 seconds

No hardware required. You need Python 3 and a C++ compiler.

```bash
# Compile the production C++, serve it on localhost, open a browser
make simulator

# A second production firmware: A/touch starts and pauses, B resets
make simulator FIRMWARE=99_stopwatch

# Native runner, process bridge, golden frames, and UI regression tests
make simulator-test
```

<img src="docs/images/simulator-ui.png" alt="The browser simulator: the round device on the left, scenario controls and a protocol log on the right" width="820">

There is also a three-pane desktop Workbench and a macOS app that needs neither Python nor a localhost server.

```bash
make workbench-install     # first time only
make workbench             # firmware switching, Inspector, event timeline
make macos-app             # the self-contained M5Stack Simulator.app
```

## Checking the screen without hardware

`scenarios/*.sim` are replay scripts written in exactly the commands the UI sends: buttons, touch coordinates, virtual time, scenario, and shots.

```text
# scenarios/sokkon-touch-ring.sim
TOUCH 233 60      # outside the ring; the firmware should ignore it
SHOT outside-ring
TOUCH 233 233     # dead centre; the focus timer starts
ADVANCE 3000
SHOT inside-ring
```

```bash
make session SCRIPT=scenarios/sokkon-face.sim
```

<img src="docs/images/session-contact-sheet.png" alt="A contact sheet of five device screens captured in one run" width="900">

`.simulator/sessions/` receives `report.json` and a `contact-sheet.png` holding every shot. Starting a browser costs far more than the drawing does, so a whole session is one launch.

The findings in `report.json` are geometric facts, not taste.

| severity | meaning |
| --- | --- |
| `error` | outside the 466 × 466 framebuffer, outside the **round** AMOLED's visible circle, two strings sharing pixels, or text with no published geometry |
| `notice` | a string painted over by a later filled shape — a toast, or a line nobody meant to hide |

`test_simulator/golden/` locks the frames each scenario draws, so an unintended layout change fails a test. When the change is intended, run `make golden-update` and review the diff before committing. Anything you do in the browser can be captured with `python3 -m simulator --record path.sim` and replayed as a script.

Sensors travel the same path. Below, three shots at different tilts show the accelerometer `99_stopwatch` actually read.

<img src="docs/images/session-stopwatch-tilt.png" alt="Three shots at different tilts; the IMU readout changes from X+0.12 Y-0.08 to X+0.60 Y-0.30 to X-0.75 Y+0.40" width="900">

## How it works

```text
firmware/apps/10_sokkon/main.cpp ─┐
firmware/shared/board.cpp ─────────┼─ host C++ compiler ─ native runner
Arduino / M5Unified / ESP32 HAL ───┘                         │
                                                            ├─ framebuffer draw commands
browser canvas ◀─ localhost HTTP API ◀─ Python process bridge┼─ protocol / haptic log
                                                            └─ screen / pending state
```

The thin HAL in `simulator/native/include/` replaces only the Arduino, M5Unified, and ESP32 APIs. `setup()` and `loop()`, the button branches, touch hit-testing, mode cycling, the focus timer, USB protocol v2, the pending queue, the five-second host timeout, the thirty-second unknown result, the two-minute dim, the ten-minute sleep, and the screen layout are all executed by the production C++.

Everything a runner does not decide — NDJSON encoding, the log ring, scenarios, time scaling, the command loop — lives in `sim_host.hpp`, so a runner is only the semantics of one production firmware. Adding a third means subclassing `sim_host::Host` and writing its `FirmwareIdentity` and `screen` block.

See [Mac Simulator](docs/SIMULATOR.md) for the full picture.

## On real hardware — SOKKON / 即今

Connect over USB Type-C and start the companion, which uses only the standard library. The companion itself never talks to the network; it shows the frontmost app name on the device as your current context. Note that the default `Documents` destination may be synced by macOS or iCloud depending on your settings.

```bash
# First time only: back up the factory flash, then write SOKKON
make build ENV=10_sokkon
make flash ENV=10_sokkon PORT=/dev/cu.usbmodemXXXX

# First time only: pair the physically attached device ID to this Mac
make companion-pair ARGS="--port /dev/cu.usbmodemXXXX"

# Daily use after pairing
make companion
```

| Input | Result |
| --- | --- |
| Yellow A | MARK the time, mode, frontmost app, and focus duration into `~/Documents/Sokkon Inbox.md` |
| Blue B | Cycle `NOW → BUILD → READ → MEET → PRESENT → REST` |
| Screen centre | Start or pause the focus timer |

MARK returns its firm confirmation haptic only after the Mac has `fsync`ed the Markdown. Being disconnected and an explicit save failure both mean "not saved", but when nothing answers within thirty seconds the device shows `SAVE UNKNOWN`, because only the reply may have been lost. No arbitrary shell runs; the only extra actions are macOS Shortcuts named explicitly in a JSON config. See [SOKKON design](docs/SOKKON.md) for the protocol and the privacy boundary.

## First ten minutes with a device

Use a USB Type-C cable that carries data. **Back up the factory firmware before your first write.**

```bash
# Put the device in download mode, then use the port it prints
./scripts/detect-port.sh
make device-info PORT=/dev/cu.usbmodemXXXX
make backup PORT=/dev/cu.usbmodemXXXX

# Build and flash the minimal diagnostic
make build ENV=00_smoke
make flash ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
make monitor ENV=00_smoke PORT=/dev/cu.usbmodemXXXX
```

For download mode, hold the power button for about two seconds after connecting USB and release once the internal green LED lights. See [flashing and recovery](docs/FLASHING.md).

## Hardware

| Item | Detail |
| --- | --- |
| MCU | ESP32-S3R8, dual-core LX7 up to 240 MHz |
| Memory | 16 MB flash, 8 MB PSRAM |
| Display | 1.75 inch, 466 × 466, round AMOLED (CO5300) |
| Input | CST820B touch, two programmable buttons, power button |
| Motion | BMI270 (3-axis accelerometer + 3-axis gyroscope, no magnetometer) |
| Audio | MEMS microphone, ES8311 codec, 1 W / 8 Ω speaker |
| Other | RX8130CE RTC, vibration motor, M5PM1 power management, 450 mAh battery |
| Radio | 2.4 GHz Wi-Fi. Bluetooth LE is confirmed as an ESP32-S3 SoC capability from chip information; GATT behaviour on this product is unverified |
| Expansion | Port A (G10 / G11) and a rear 2.54 mm bus |

There is no heart rate, SpO2, GPS/GNSS, environmental sensor, camera, or microSD. No water resistance rating is confirmed in the official specification, so treat the device as one that must stay dry. See [hardware notes](docs/HARDWARE.md).

## Firmware environments

| PlatformIO environment | What it exercises |
| --- | --- |
| `00_smoke` | Minimal board, display, and input bring-up |
| `01_display_input` | AMOLED, touch, both buttons |
| `02_imu` | BMI270 accelerometer and gyroscope |
| `03_rtc_power` | RTC, battery, power information |
| `04_audio_haptics` | Microphone, speaker, vibration |
| `05_wifi_scan` | 2.4 GHz Wi-Fi scan |
| `07_ble_gatt` | Bluetooth LE GATT |
| `08_external_i2c` | I2C scan on Port A |
| `10_sokkon` | The Mac-connected 即今 interface (default) |
| `99_stopwatch` | The stopwatch itself |
| `native` | Host-side logic unit tests |

## Commands

| Command | What it does |
| --- | --- |
| `make simulator` | Compile the production C++ and open the browser simulator |
| `make workbench` | Start the three-pane Firmware Workbench |
| `make session SCRIPT=…` | Replay a session, writing `report.json` and a contact sheet |
| `make session-report SCRIPT=…` | Replay without a browser and report only what the panel cannot show |
| `make golden-update` | Re-record golden frames after an intended layout change |
| `make font-metrics` | Re-measure the device font metrics |
| `make simulator-test` | Native runner, bridge, golden frame, and UI regression tests |
| `make workbench-test` | Shared renderer, transport, and Sites package tests |
| `make companion-test` | Mac companion unit and PTY integration tests |
| `make build-all` / `make test` | Build every firmware / run hardware-independent logic tests |
| `make macos-app` / `make macos-dmg` | The self-contained .app / a local DMG |
| `make backup` / `make flash` / `make monitor` | Back up, write, and watch a real device |

## Distribution

`M5Stack Simulator.app` bundles the Workbench, the typed Swift bridge, and both native runners. To sign and ship it:

```bash
# Sign with a Developer ID Application certificate and build the DMG
make macos-release IDENTITY="Developer ID Application: NAME (TEAMID)"

# Store the credentials in your keychain once (run this yourself)
#   xcrun notarytool store-credentials m5stack-simulator --apple-id ... --team-id ... --password ...
make macos-notarize PROFILE=m5stack-simulator
```

`macos-notarize` notarizes the app first and staples the bundle, then rebuilds the DMG around the stapled app and notarizes that. A ticket stapled to a disk image does not travel with the app someone drags out of it, so any other order leaves a first launch offline refused by Gatekeeper. The script finishes by checking the verdict for a download, quarantine attribute and all.

A DMG built with `make macos-dmg` alone is only ad-hoc signed and will be stopped on another Mac. See [macOS app](macos/M5StackSimulator/README.md) for the trust boundary.

## Repository layout

```text
firmware/apps/          Per-feature firmware
firmware/shared/        Shared board bring-up and logic
simulator/native/       Native HAL and the runners on the shared host framework
simulator/static/       The browser UI and the renderer both UIs share
simulator/workbench/    The three-pane Firmware Workbench (React)
scenarios/              Replayable session scripts
test_simulator/golden/  The frames each scenario is known to draw
companion/              The dependency-free macOS USB companion
macos/                  Build definitions for the self-contained app and DMG
scripts/                Build, font measurement, port detection, backup, flashing
docs/                   Hardware, development, simulator, recovery, references
platformio.ini          Pinned build environments and dependencies
```

## Documentation

- [How the Mac simulator works and what it guarantees](docs/SIMULATOR.md)
- [SOKKON design and USB protocol v2](docs/SOKKON.md)
- [Development environment and coding workflow](docs/DEVELOPMENT.md)
- [Flashing, backup, and factory recovery](docs/FLASHING.md)
- [Hardware notes](docs/HARDWARE.md) / [Project ideas](docs/PROJECT_IDEAS.md) / [Primary sources](docs/REFERENCES.md)
- [Working agreement for agents](AGENTS.md)

Most documents under `docs/` are written in Japanese.

## License

MIT (see [LICENSE](LICENSE)). Dependencies and the provenance of the generated font measurements are recorded in [NOTICE.md](NOTICE.md). No glyph bitmaps are copied into this repository.
