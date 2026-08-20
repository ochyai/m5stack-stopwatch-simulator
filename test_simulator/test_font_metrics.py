"""Device font parity for the compiler-driven simulator.

The firmware branches on `textWidth` — `10_sokkon` truncates context and detail
lines until they fit a pixel budget — so an approximated text measurement makes
the simulator disagree with the panel about what is on screen.  These tests
drive the real runner and check that every string is measured and placed with
the device's own metrics.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
import unittest

from test_native_runner import BUILD_SCRIPT, NativeRunner, ROOT


def load_generator() -> types.ModuleType:
  """Import the hyphenated generator script by path."""
  path = ROOT / "scripts" / "generate-font-metrics.py"
  specification = importlib.util.spec_from_file_location("font_metrics_generator", path)
  assert specification is not None and specification.loader is not None
  module = importlib.util.module_from_spec(specification)
  # dataclasses resolve their annotations through sys.modules, so a
  # path-loaded module has to be registered before it executes.
  sys.modules[specification.name] = module
  specification.loader.exec_module(module)
  return module


CONTEXT_MAX_WIDTH = 300  # firmware/apps/10_sokkon/main.cpp drawFittedString
DETAIL_MAX_WIDTH = 260


def draw_strings(snapshot: dict[str, object]) -> list[dict[str, object]]:
  frame = snapshot.get("frame")
  commands = frame.get("commands") if isinstance(frame, dict) else None
  if not isinstance(commands, list):
    raise AssertionError("snapshot has no frame commands")
  return [
    command
    for command in commands
    if isinstance(command, dict) and command.get("op") == "drawString"
  ]


def find_text(snapshot: dict[str, object], prefix: str) -> dict[str, object]:
  for command in draw_strings(snapshot):
    text = command.get("text")
    if isinstance(text, str) and text.startswith(prefix):
      return command
  raise AssertionError(f"no drawString starting with {prefix!r}")


class DeviceFontMetricsTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    result = subprocess.run(
      [str(BUILD_SCRIPT)],
      cwd=ROOT,
      text=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      timeout=120,
      check=False,
    )
    if result.returncode != 0:
      raise AssertionError(f"native build failed:\n{result.stdout}")

  def test_generated_metrics_match_the_installed_package(self) -> None:
    """The committed header must still describe the fonts M5GFX ships."""
    generator = load_generator()
    try:
      fonts_directory, _version = generator.find_package()
    except generator.GeneratorError as error:
      self.skipTest(f"M5GFX is not installed: {error}")

    measured = generator.collect(fonts_directory)
    committed = generator.OUTPUT.read_text(encoding="utf-8")
    for font in measured:
      self.assertIn(f'"{font.name}", {font.height}, {font.baseline}', committed)

  def test_every_drawn_string_publishes_the_device_pen_grid(self) -> None:
    with NativeRunner() as runner:
      snapshot = runner.command("SNAPSHOT")

    commands = draw_strings(snapshot)
    self.assertGreater(len(commands), 4, "the SOKKON face draws several strings")
    for command in commands:
      text = str(command["text"])
      layout = command.get("layout")
      self.assertIsInstance(layout, dict, f"{text!r} has no device layout")
      assert isinstance(layout, dict)

      printable = [character for character in text if character >= " "]
      pen = layout["pen"]
      self.assertIsInstance(pen, list)
      assert isinstance(pen, list)
      self.assertEqual(len(pen), len(printable), f"{text!r} pen grid length")
      self.assertEqual(pen, sorted(pen), f"{text!r} pen grid must advance")
      self.assertEqual(pen[0], layout["left"], f"{text!r} starts at its left edge")

      # A centred string is anchored on the panel's own centre line.
      if command["datum"] == "middle_center":
        centre = layout["left"] + layout["width"] // 2
        self.assertLessEqual(abs(centre - int(command["x"])), 1, f"{text!r} centring")

      self.assertGreater(layout["height"], 0)
      self.assertGreater(layout["baseline"], layout["top"])

  def test_measurements_are_the_devices_own_numbers(self) -> None:
    """Regression values measured from M5GFX, not from a character-count guess."""
    with NativeRunner() as runner:
      snapshot = runner.command("SNAPSHOT")

    clock = find_text(snapshot, "12:34")
    self.assertEqual(clock["font"], "FreeSansBold24pt7b")
    self.assertEqual(clock["layout"]["width"], 116)
    self.assertEqual(clock["layout"]["height"], 47)

    elapsed = find_text(snapshot, "00:00:00.00")
    self.assertEqual(elapsed["font"], "FreeSansBold18pt7b")
    self.assertEqual(elapsed["layout"]["width"], 179)
    self.assertEqual(elapsed["layout"]["height"], 33)

    mark = find_text(snapshot, "MARK")
    self.assertEqual(mark["font"], "Font2")
    self.assertEqual(mark["layout"]["width"], 34)
    self.assertEqual(mark["layout"]["height"], 16)

  def test_a_long_detail_is_truncated_at_the_devices_pixel_budget(self) -> None:
    long_detail = "REFACTORING THE SIMULATOR HOST FRAMEWORK AND RENDERER"
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tDETAIL\t" + long_detail)
      snapshot = runner.command("SNAPSHOT")

    drawn = find_text(snapshot, "REFACTORING")
    self.assertNotEqual(drawn["text"], long_detail, "the panel cannot show it all")
    self.assertTrue(str(drawn["text"]).endswith("..."))
    self.assertLessEqual(drawn["layout"]["width"], DETAIL_MAX_WIDTH)

    # One more character would have to overflow, or the fit is not tight.
    self.assertGreater(drawn["layout"]["width"], DETAIL_MAX_WIDTH - 40)

  def test_a_short_detail_is_left_alone(self) -> None:
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tDETAIL\tSHORT")
      snapshot = runner.command("SNAPSHOT")

    drawn = find_text(snapshot, "SHORT")
    self.assertEqual(drawn["text"], "SHORT")
    self.assertLess(drawn["layout"]["width"], CONTEXT_MAX_WIDTH)


class PanelInputTest(unittest.TestCase):
  """A press has a position, and the firmware reads it."""

  @classmethod
  def setUpClass(cls) -> None:
    result = subprocess.run(
      [str(BUILD_SCRIPT)],
      cwd=ROOT,
      text=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      timeout=120,
      check=False,
    )
    if result.returncode != 0:
      raise AssertionError(f"native build failed:\n{result.stdout}")

  def test_only_a_press_inside_the_focus_ring_starts_the_timer(self) -> None:
    with NativeRunner() as runner:
      start = runner.command("SNAPSHOT")
      # 173 px above the centre: inside the panel, outside the 145 px ring.
      outside = runner.command("TOUCH\t233\t60")
      inside = runner.command("TOUCH\t233\t233")

    self.assertFalse(start["screen"]["focus_running"])
    self.assertFalse(outside["screen"]["focus_running"], "a press outside the ring must not toggle")
    self.assertTrue(inside["screen"]["focus_running"])

  def test_a_touch_outside_the_panel_is_refused(self) -> None:
    with NativeRunner() as runner:
      for command in ("TOUCH\t466\t0", "TOUCH\t0\t999", "TOUCH\t233", "TOUCH\tx\ty"):
        snapshot = runner.command(command)
        self.assertTrue(snapshot.get("command_error"), f"{command} should be refused")
      # The process stays usable after refusing bad input.
      self.assertIn("screen", runner.command("SNAPSHOT"))


if __name__ == "__main__":
  unittest.main()
