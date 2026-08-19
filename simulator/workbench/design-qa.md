# Firmware Workbench — Design QA

## Target and comparison

- Reference: `reference/firmware-workbench.png`
- Implementation capture: `qa/implementation-final-1487x1058.png` (local QA artifact, intentionally git-ignored)
- Comparison viewport: 1487 × 1058 for both images
- Compact viewport: 1120 × 760, matching the native window minimum
- Device asset: `public/device-shell.png` with the production canvas composited into its circular screen

The reference and implementation were inspected together at the same viewport and state. The implementation preserves the reference's three-column desktop workbench, 98 px native-style toolbar, large central C152, right inspector, and 268 px event timeline. The real shell raster keeps the yellow upper-left button and blue upper-right button visible in their measured positions.

## Findings resolved

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | Early shell cropping hid or displaced the physical buttons. | Reframed the full raster around the circular screen and placed transparent A/B hit targets over the measured upper side-button regions. |
| P2 | Initial panel and timeline proportions did not match the selected reference. | Matched the reference toolbar, responsive column clamps, central device scale, and timeline height at 1487 × 1058. |
| P2 | Several reference controls looked actionable but did not communicate their state. | Implemented firmware search/filter, inspector navigation, tabs, timeline filters/clear, restart/stop, time controls, charging and battery controls; unavailable target/install/build-option controls are explicitly disabled. |
| P2 | Timeline Clear could lose future entries after the native 120-entry log rolled over. | Replaced a fixed index cutoff with a suffix/prefix overlap watermark and added capped-log regression coverage. |

## Core interaction checks

| Journey | Result |
| --- | --- |
| Switch `99_stopwatch` → `10_sokkon` → `99_stopwatch` | Passed; each selection uses the fixed registry and returns the newly booted production snapshot. |
| Build & Run active firmware | Passed; same-ID selection recompiles/restarts transactionally instead of returning a cached process. |
| Yellow A, blue B, center touch and A/B/Space keys | Passed; actions reach production C++ branches and update the canvas/timeline. |
| Device / Logs / Inspector tabs | Passed. |
| Inspector Inputs / Display / System navigation | Passed, including compact-height scrolling. |
| Battery, charging, virtual-time scale and offsets | Passed. |
| Firmware search and active-only filter | Passed. |
| Timeline category filters and persistent Clear | Passed, including new events after a capped 120-entry rollover. |
| Screenshot | Passed in browser; native shell additionally validates a bounded PNG and presents a macOS save panel. |

## Quality checks

- No clipped panels or overlapping controls at 1487 × 1058 or 1120 × 760.
- Keyboard focus rings and accessible names are present for the primary controls.
- Canvas rendering uses the native firmware draw-command stream; the device face is not a static mock.
- Browser console inspection produced no application errors.
- Workbench production build and its transport/Sites/timeline tests pass.
- The packaged native shell uses the real macOS titlebar and traffic-light controls; the HTML toolbar reserves the corresponding safe inset.

final result: passed
