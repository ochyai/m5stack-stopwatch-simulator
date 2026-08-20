"""Unit tests for scripted sessions, inspection, and shot rendering.

These run without a native binary and without a browser: the script grammar,
the geometry findings, and the generated page are all pure functions.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any
import unittest
import unittest.mock

from simulator import screenshot
from simulator.session import (
  DEVICE_SIZE,
  ScriptRecorder,
  SessionError,
  Step,
  format_script,
  inspect_frame,
  parse_script,
  run_session,
)


def text_command(
  text: str,
  left: int,
  top: int,
  width: int,
  height: int = 16,
) -> dict[str, Any]:
  return {
    "op": "drawString",
    "text": text,
    "x": left + width // 2,
    "y": top + height // 2,
    "font": "Font2",
    "datum": "middle_center",
    "layout": {
      "left": left,
      "top": top,
      "baseline": top + 13,
      "width": width,
      "height": height,
      "pen": [left],
    },
  }


class ScriptGrammarTest(unittest.TestCase):
  def test_a_script_parses_every_supported_command(self) -> None:
    steps = parse_script(
      "\n".join(
        [
          "# a comment",
          "",
          "NOTE why this session exists",
          "ACTION mark",
          "ADVANCE 6000",
          "CONFIGURE context CODEX AT WORK  # trailing comments stay out of values",
          "CONFIGURE connected false",
          "CONFIGURE battery_percent 7",
          "CONFIGURE time_scale 2.5",
          "CONFIGURE host_mode build",
          "RESET",
          "SHOT after-reset",
        ]
      )
    )
    kinds = [step.kind for step in steps]
    self.assertEqual(
      kinds,
      ["note", "action", "advance", "configure", "configure", "configure", "configure", "configure", "reset", "shot"],
    )
    self.assertEqual(steps[1].argument, "mark")
    self.assertEqual(steps[2].value, 6000)
    self.assertEqual(steps[3].value, "CODEX AT WORK")
    self.assertIs(steps[4].value, False)
    self.assertEqual(steps[5].value, 7)
    self.assertEqual(steps[6].value, 2.5)
    self.assertEqual(steps[7].value, "BUILD")
    self.assertEqual(steps[9].argument, "after-reset")

  def test_a_full_line_comment_never_becomes_a_value(self) -> None:
    steps = parse_script("#CONFIGURE context NOPE\nACTION mode\n")
    self.assertEqual([step.kind for step in steps], ["action"])

  def test_scripts_are_rejected_with_the_offending_line(self) -> None:
    for script, fragment in (
      ("ACTION explode", "unknown action"),
      ("ADVANCE soon", "whole number"),
      ("ADVANCE -5", "between 0 and"),
      ("ADVANCE 999999999", "between 0 and"),
      ("CONFIGURE nonsense 1", "unknown scenario key"),
      ("CONFIGURE battery_percent high", "must be an integer"),
      ("CONFIGURE connected maybe", "must be true or false"),
      ("CONFIGURE host_mode SLEEP", "host_mode must be one of"),
      ("CONFIGURE outcome LATER", "outcome must be"),
      ("SHOT bad label", "letters, digits"),
      ("TELEPORT 1", "unknown command"),
      ("CONFIGURE", "needs a key and a value"),
    ):
      with self.subTest(script=script):
        with self.assertRaises(SessionError) as raised:
          parse_script(script)
        self.assertIn(fragment, str(raised.exception))

  def test_steps_render_back_into_a_replayable_script(self) -> None:
    original = "ACTION focus\nADVANCE 250\nCONFIGURE connected true\nRESET\nSHOT done\n"
    steps = parse_script(original)
    rendered = format_script(steps)
    self.assertEqual(parse_script(rendered), steps)
    self.assertIn("CONFIGURE connected true", rendered)

  def test_a_header_is_written_as_comments(self) -> None:
    rendered = format_script(parse_script("ACTION mark"), header="why\nthis exists")
    self.assertTrue(rendered.startswith("# why\n# this exists\n"))
    self.assertEqual(len(parse_script(rendered)), 1)


class FrameInspectionTest(unittest.TestCase):
  def test_a_well_placed_frame_has_nothing_to_report(self) -> None:
    frame = {"commands": [text_command("CENTRED", 200, 220, 60)]}
    self.assertEqual(inspect_frame(frame), [])

  def test_text_leaving_the_framebuffer_is_an_error(self) -> None:
    frame = {"commands": [text_command("TOO WIDE", 400, 220, 120)]}
    findings = inspect_frame(frame)
    self.assertEqual(findings[0]["kind"], "offscreen_text")
    self.assertEqual(findings[0]["severity"], "error")

  def test_text_in_the_corner_of_a_round_panel_is_an_error(self) -> None:
    # Inside the 466 x 466 buffer, outside the circle the panel can show.
    frame = {"commands": [text_command("CORNER", 4, 4, 60)]}
    findings = inspect_frame(frame)
    self.assertEqual(findings[0]["kind"], "outside_round_panel")
    self.assertIn("round", findings[0]["detail"])

  def test_two_strings_sharing_pixels_are_an_error(self) -> None:
    frame = {
      "commands": [
        text_command("FIRST", 200, 220, 60),
        text_command("SECOND", 230, 226, 60),
      ]
    }
    findings = [f for f in inspect_frame(frame) if f["kind"] == "overlapping_text"]
    self.assertEqual(len(findings), 1)
    self.assertEqual(findings[0]["other"], "SECOND")

  def test_a_later_filled_shape_over_a_string_is_reported_as_a_notice(self) -> None:
    frame = {
      "commands": [
        text_command("UNDER THE TOAST", 180, 220, 100),
        {"op": "fillRoundRect", "x": 175, "y": 215, "w": 120, "h": 30, "r": 15},
      ]
    }
    findings = [f for f in inspect_frame(frame) if f["kind"] == "occluded_text"]
    self.assertEqual(len(findings), 1)
    self.assertEqual(findings[0]["severity"], "notice")
    self.assertEqual(findings[0]["by"], "fillRoundRect")

  def test_a_shape_drawn_before_a_string_does_not_hide_it(self) -> None:
    frame = {
      "commands": [
        {"op": "fillRoundRect", "x": 175, "y": 215, "w": 120, "h": 30, "r": 15},
        text_command("ON TOP OF THE PILL", 180, 220, 100),
      ]
    }
    self.assertEqual(inspect_frame(frame), [])

  def test_text_without_device_geometry_is_an_error(self) -> None:
    frame = {"commands": [{"op": "drawString", "text": "UNMEASURED", "x": 1, "y": 1}]}
    findings = inspect_frame(frame)
    self.assertEqual(findings[0]["kind"], "unmeasured_text")

  def test_blank_strings_and_non_text_commands_are_ignored(self) -> None:
    frame = {
      "commands": [
        {"op": "fillScreen", "color": 0},
        {"op": "drawString", "text": "   ", "x": 0, "y": 0},
        "not a command",
      ]
    }
    self.assertEqual(inspect_frame(frame), [])


class RecordingBackend:
  """Minimal stand-in that records the calls a session makes."""

  def __init__(self, snapshot: dict[str, Any] | None = None) -> None:
    self.calls: list[tuple[str, Any]] = []
    self._snapshot = snapshot or {
      "screen": {"mode": "NOW", "elapsed_text": "00:00:00.00"},
      "frame": {"commands": [text_command("CENTRED", 200, 220, 60)]},
    }

  def _record(self, name: str, argument: Any = None) -> dict[str, Any]:
    self.calls.append((name, argument))
    return self._snapshot

  def snapshot(self) -> dict[str, Any]:
    return self._record("snapshot")

  def freeze_time(self, frozen: bool) -> dict[str, Any]:
    return self._record("freeze_time", frozen)

  def perform_action(self, action: str) -> dict[str, Any]:
    return self._record("perform_action", action)

  def advance(self, milliseconds: int) -> dict[str, Any]:
    return self._record("advance", milliseconds)

  def configure(self, mapping: dict[str, Any]) -> dict[str, Any]:
    return self._record("configure", mapping)

  def reset(self) -> dict[str, Any]:
    return self._record("reset")


class SessionReplayTest(unittest.TestCase):
  def test_a_replay_freezes_time_and_dispatches_every_step(self) -> None:
    backend = RecordingBackend()
    steps = parse_script(
      "ACTION mark\nADVANCE 500\nCONFIGURE context CODEX\nNOTE why\nSHOT one\n"
    )
    result = run_session(backend, steps, firmware_id="10_sokkon")

    self.assertEqual(backend.calls[0], ("freeze_time", True))
    self.assertIn(("perform_action", "mark"), backend.calls)
    self.assertIn(("advance", 500), backend.calls)
    self.assertIn(("configure", {"context": "CODEX"}), backend.calls)
    self.assertEqual(result.notes, ["why"])
    self.assertEqual([shot.label for shot in result.shots], ["one"])
    self.assertEqual(result.errors, [])

  def test_a_reset_returns_to_frozen_time(self) -> None:
    backend = RecordingBackend()
    run_session(backend, parse_script("RESET\n"), firmware_id="10_sokkon")
    self.assertEqual(backend.calls[-2:], [("reset", None), ("freeze_time", True)])

  def test_a_refused_command_stops_the_replay_at_its_line(self) -> None:
    backend = RecordingBackend({"command_error": "unsupported action", "screen": {}, "frame": {}})
    with self.assertRaises(SessionError) as raised:
      run_session(backend, parse_script("ACTION wake\n"), firmware_id="10_sokkon")
    self.assertIn("line 1", str(raised.exception))
    self.assertIn("unsupported action", str(raised.exception))

  def test_a_golden_projection_keeps_only_the_panel(self) -> None:
    backend = RecordingBackend()
    result = run_session(backend, parse_script("SHOT only\n"), firmware_id="10_sokkon")
    golden = result.golden()
    self.assertEqual(golden["firmware"], "10_sokkon")
    self.assertEqual(golden["shots"][0]["label"], "only")
    self.assertIn("commands", golden["shots"][0])
    self.assertNotIn("findings", golden["shots"][0])


class ScriptRecorderTest(unittest.TestCase):
  def test_a_recording_replays_as_a_script(self) -> None:
    with tempfile.TemporaryDirectory() as workspace:
      path = Path(workspace) / "nested" / "session.sim"
      recorder = ScriptRecorder(path)
      recorder.record_action("mark")
      recorder.record_action("advance_30s")
      recorder.record_action("reset")
      recorder.record_action("not_an_action")
      recorder.record_configuration({"context": "CODEX", "charging": True, "ignored": 1})
      label = recorder.record_shot()

      text = path.read_text(encoding="utf-8")
      self.assertIn("python3 -m simulator.session", text)
      steps = parse_script(text)
      self.assertEqual(
        [step.render() for step in steps],
        [
          "ACTION mark",
          "ADVANCE 30001",
          "RESET",
          "CONFIGURE context CODEX",
          "CONFIGURE charging true",
          f"SHOT {label}",
        ],
      )

  def test_reopening_a_recording_appends_instead_of_restarting(self) -> None:
    with tempfile.TemporaryDirectory() as workspace:
      path = Path(workspace) / "session.sim"
      ScriptRecorder(path).record_action("mark")
      ScriptRecorder(path).record_action("mode")
      self.assertEqual(
        [step.render() for step in parse_script(path.read_text(encoding="utf-8"))],
        ["ACTION mark", "ACTION mode"],
      )


class ShotPageTest(unittest.TestCase):
  def test_the_page_replays_frames_with_the_shipping_renderer(self) -> None:
    panels = [
      screenshot.Panel(
        label="boot",
        frame={"commands": [text_command("HELLO", 200, 220, 60)]},
        screen={"brightness": 40},
      )
    ]
    page = screenshot.build_page(panels, labelled=True)
    renderer = screenshot.RENDERER.read_text(encoding="utf-8")
    self.assertIn("export function renderFrame", renderer)
    # The one interpreter is inlined, not reimplemented.
    self.assertIn("renderFrame(context, panel.frame)", page)
    self.assertIn("screenOpacity(panel.screen, panel.frame)", page)
    self.assertIn('"HELLO"', page)
    self.assertIn("boot", page)

  def test_a_payload_can_never_close_the_script_element(self) -> None:
    panels = [
      screenshot.Panel(label="x", frame={"commands": [text_command("</script><b>", 200, 220, 60)]})
    ]
    page = screenshot.build_page(panels)
    self.assertNotIn("</script><b>", page)
    self.assertIn("<\\/script>", page)

  def test_the_contact_sheet_grid_fits_every_panel(self) -> None:
    self.assertEqual(screenshot.sheet_size(1, labelled=False), (DEVICE_SIZE, DEVICE_SIZE, 1))
    width, height, columns = screenshot.sheet_size(5, labelled=True)
    self.assertEqual(columns, 3)
    self.assertEqual(width, 3 * DEVICE_SIZE)
    self.assertEqual(height, 2 * (DEVICE_SIZE + screenshot.LABEL_HEIGHT))

  def test_an_empty_capture_is_refused(self) -> None:
    with self.assertRaises(screenshot.ScreenshotError):
      screenshot.capture_panels([], "unused.png")

  def test_a_missing_browser_is_reported_clearly(self) -> None:
    with (
      unittest.mock.patch.object(screenshot, "BROWSER_CANDIDATES", ()),
      unittest.mock.patch.dict(os.environ, {}, clear=True),
    ):
      with self.assertRaises(screenshot.ScreenshotError) as raised:
        screenshot.find_browser("/nonexistent/browser")
    self.assertIn("no headless Chrome/Chromium", str(raised.exception))

  def test_an_explicit_browser_path_is_honoured(self) -> None:
    with tempfile.TemporaryDirectory() as workspace:
      fake = Path(workspace) / "chrome"
      fake.write_text("#!/bin/sh\n", encoding="utf-8")
      fake.chmod(0o755)
      self.assertEqual(screenshot.find_browser(str(fake)), str(fake))


if __name__ == "__main__":
  unittest.main()
