# M5Stack Simulator for macOS

`M5Stack Simulator.app` is the distributable native shell for Firmware Workbench. It embeds the
React/Vite interface in `WKWebView` and launches the same compiler-driven C++ binaries used by the
browser simulator. It does not launch a browser, Python process, localhost server, or cloud service.

```text
SwiftUI/AppKit window
└── WKWebView (bundled Workbench assets, m5sim://app/…)
    └── typed Promise bridge
        └── Swift Process bridge (stdin/stdout NDJSON)
            ├── sokkon-native ───── production 10_sokkon/main.cpp
            └── stopwatch-native ─ production 99_stopwatch/main.cpp
```

The native adapters and HAL remain transport layers. Firmware screen state, timers, button behavior,
touch behavior, protocol behavior, and draw commands continue to come from production C++.

## Build a local app

From this directory:

```bash
./scripts/build-app.sh
open "dist/M5Stack Simulator.app"

# Versioned local DMG with an Applications shortcut and SHA-256 file
./scripts/build-dmg.sh
```

The build script performs a reproducible `npm ci`, builds and tests the Workbench/Sites transport,
compiles both native runners, runs the Swift bridge tests, builds the release Swift executable, and assembles:

```text
dist/M5Stack Simulator.app/
└── Contents/
    ├── Info.plist
    ├── MacOS/M5StackSimulator
    └── Resources/
        ├── AppIcon.icns
        ├── Native/{sokkon-native,stopwatch-native}
        └── Web/{index.html,assets,…}
```

The default result is unsigned. `--adhoc-sign` applies only a local ad-hoc signature and does not make
an app suitable for public download. Useful development options are:

```bash
./scripts/build-app.sh --skip-dependency-install --skip-tests
./scripts/build-app.sh --configuration debug --adhoc-sign
./scripts/build-app.sh --version 0.2.0 --build-number 2
```

The app icon is generated from `Resources/AppIconSource.png` using the standard `sips`/`iconutil`
pipeline. A deterministic Swift ICNS container fallback handles automation sandboxes in which macOS 26
incorrectly rejects the otherwise valid iconset; it does not modify the source image.

`build-dmg.sh` never signs, notarizes, uploads, or changes the source app. Its output is named like
`M5Stack-Simulator-0.1.0-arm64-local.dmg`, making the local architecture and non-release status explicit.
It verifies that the Swift executable and both embedded C++ runners contain the same architecture slices,
then replaces only the same versioned artifact and leaves other builds in `dist/` untouched.

```bash
cd dist
shasum -a 256 -c M5Stack-Simulator-0.1.0-arm64-local.dmg.sha256
```

For `swift run`, first build both runners and the Workbench, or point the app at explicit roots:

```bash
M5STACK_SIMULATOR_WEB_ROOT=/absolute/path/to/dist/client \
M5STACK_SIMULATOR_NATIVE_ROOT=/absolute/path/to/.simulator \
swift run --disable-sandbox --package-path macos/M5StackSimulator M5StackSimulator
```

These overrides are development conveniences. Packaged builds resolve only their own `Contents/Resources`
unless an environment override is deliberately supplied at launch.

## JavaScript bridge contract

At document start the app installs `window.m5stackSimulator`. The Workbench should prefer it when
`window.m5stackSimulator.available === true` and retain its HTTP transport only as a browser fallback.
There is no method for arbitrary runner commands, paths, arguments, or shell execution.

```js
await window.m5stackSimulator.capabilities();
await window.m5stackSimulator.snapshot();
await window.m5stackSimulator.selectFirmware("10_sokkon"); // or 99_stopwatch
await window.m5stackSimulator.reset();
await window.m5stackSimulator.action("mark");              // mark|mode|focus|wake
await window.m5stackSimulator.advance(6001);
await window.m5stackSimulator.configure("battery_percent", 84);
```

Supported configuration keys are `connected`, `outcome`, `latency_ms`, `context`, `detail`,
`host_mode`, `battery_percent`, `charging`, and `time_scale`. Values are type/range checked in Swift,
then encoded as one existing `CONFIGURE` protocol line. Each state operation resolves to the complete
runner snapshot object and dispatches `m5stack-simulator-snapshot` on `window` with that snapshot in
`event.detail`. Invalid input, runner failure, timeout, identity mismatch, or runner `command_error`
rejects the Promise.

Firmware switching is transactional. A candidate runner must launch, answer `SNAPSHOT`, and report the
requested allowlisted firmware ID before the current runner is stopped. If any check fails, the current
firmware and process continue running. Selecting the active ID also boots a fresh candidate. The native
Workbench labels this operation **Restart Firmware**, because a distributed app restarts its bundled
runner rather than claiming to compile source on the recipient's Mac. The browser Workbench's
**Build & Run** remains the source-compiling path through the Python backend.

The app also sets these integration signals:

- `data-m5sim-native="macos"` on `<html>`
- `--m5sim-titlebar-safe-left: 78px`
- `--m5sim-titlebar-height: 38px`
- `m5stack-simulator-ready` event

The window uses a transparent full-size native titlebar. Workbench toolbar content should respect the
left safe inset so it does not overlap the real macOS traffic-light controls; a second HTML titlebar is
not needed.

## Trust and lifecycle boundaries

- Firmware IDs and executable names are a fixed Swift enum; web content cannot choose a path.
- Runner input is a typed command enum. Tabs, newlines, carriage returns, and NUL are rejected in values.
- Only one request is in flight per runner. A partial-write, timeout, oversized frame, or malformed
  snapshot permanently stops that runner so later bytes cannot be mistaken for another response.
- Snapshots are limited to 4 MiB and must be a top-level JSON object with the requested firmware ID.
- Web resources are limited to the bundled root; `..`, encoded traversal, backslashes, and escaping
  symlinks are rejected.
- Screenshot downloads accept only an explicit bounded `data:image/png;base64` navigation, validate the
  PNG response, sanitize its filename, and always require a native macOS save-panel destination.
- App termination synchronously closes runner stdin, then uses bounded TERM/KILL fallback only for its
  own child process.
- No App Sandbox entitlement is used. Outside the Mac App Store, this lets the app launch its embedded,
  separately signed runner executables without requesting unrelated device or network permissions.

## Developer ID distribution later

This repository currently has no license and this Mac currently has no valid Developer ID identity, so
the build does not claim public redistributability and does not attempt release signing. Before external
distribution:

1. Decide and add a repository license; audit npm and firmware dependency licenses.
2. Produce every executable for each supported architecture. The current local package is native-arch
   only (`arm64` on Apple Silicon); a universal release needs both Swift and C++ runner slices.
3. Sign each nested runner first, then the main executable and app with `Developer ID Application`,
   hardened runtime, timestamping, and no `--deep` shortcut. No entitlements are currently required.
4. Zip with `ditto`, submit with `xcrun notarytool`, staple the ticket, then verify with `codesign`,
   `spctl`, and a clean macOS account.

Signing credentials and notary profiles belong in the developer keychain or CI secret store, never in
this repository or the `.app` bundle.

## Tests

```bash
swift test --disable-sandbox --package-path macos/M5StackSimulator
```

Tests cover JSON framing, firmware identity, command injection boundaries, frame/advance limits,
process startup plus write/timeout cleanup, transactional firmware switching, web-resource traversal,
and the bounded screenshot-download policy.
