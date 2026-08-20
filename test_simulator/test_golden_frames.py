"""Golden frames for every committed scenario.

A golden file records what the production firmware actually drew for a scripted
session: the screen state and the exact draw commands, including the device text
geometry.  An unintended layout change therefore fails here instead of reaching
a panel, and an intended one shows up as a reviewable diff.

Refresh after a deliberate change:

    make golden-update
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from simulator.backend import NativeSimulatorBackendManager
from simulator.session import (
  default_firmware_for,
  inspect_frame,
  load_script,
  run_session,
)


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"
GOLDEN = Path(__file__).resolve().parent / "golden"
UPDATING = os.environ.get("UPDATE_GOLDEN") == "1"


def scenario_files() -> list[Path]:
  return sorted(SCENARIOS.glob("*.sim"))


def replay(scenario: Path) -> dict[str, object]:
  firmware_id = default_firmware_for(scenario)
  steps = load_script(scenario)
  with NativeSimulatorBackendManager(firmware_id=firmware_id) as backend:
    return run_session(backend, steps, firmware_id=firmware_id).golden()


def encode(golden: dict[str, object]) -> str:
  return json.dumps(golden, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


class GoldenFrameTest(unittest.TestCase):
  def test_the_repository_ships_scenarios_to_lock(self) -> None:
    self.assertTrue(scenario_files(), "no scenarios under scenarios/")

  def test_every_scenario_matches_its_golden_frames(self) -> None:
    GOLDEN.mkdir(exist_ok=True)
    for scenario in scenario_files():
      with self.subTest(scenario=scenario.name):
        produced = replay(scenario)
        golden_path = GOLDEN / f"{scenario.stem}.json"
        if UPDATING:
          golden_path.write_text(encode(produced), encoding="utf-8")
          continue
        self.assertTrue(
          golden_path.is_file(),
          f"{golden_path.name} is missing; run `make golden-update`",
        )
        expected = json.loads(golden_path.read_text(encoding="utf-8"))
        self.assertEqual(
          produced,
          expected,
          f"{scenario.name} no longer draws its golden frames; "
          "review the change and run `make golden-update` if it is intended",
        )

  def test_replay_is_deterministic(self) -> None:
    """The same script must produce the same frames on every run."""
    scenario = SCENARIOS / "sokkon-face.sim"
    self.assertEqual(replay(scenario), replay(scenario))

  def test_golden_frames_carry_device_text_geometry(self) -> None:
    """A golden without layout data would not lock what a reader sees."""
    if UPDATING:
      self.skipTest("goldens are being rewritten")
    for scenario in scenario_files():
      golden_path = GOLDEN / f"{scenario.stem}.json"
      if not golden_path.is_file():
        continue
      golden = json.loads(golden_path.read_text(encoding="utf-8"))
      strings = [
        command
        for shot in golden["shots"]
        for command in shot["commands"]
        if command.get("op") == "drawString"
      ]
      self.assertTrue(strings, f"{scenario.name} draws no text")
      for command in strings:
        self.assertIn("layout", command, f"{scenario.name}: {command['text']!r}")

  def test_no_scenario_pushes_content_off_the_round_panel(self) -> None:
    """The visible area is the inscribed circle of the 466 x 466 panel."""
    if UPDATING:
      self.skipTest("goldens are being rewritten")
    for scenario in scenario_files():
      golden_path = GOLDEN / f"{scenario.stem}.json"
      if not golden_path.is_file():
        continue
      golden = json.loads(golden_path.read_text(encoding="utf-8"))
      for shot in golden["shots"]:
        findings = inspect_frame({"commands": shot["commands"]})
        errors = [finding for finding in findings if finding.get("severity") == "error"]
        self.assertEqual(
          errors,
          [],
          f"{scenario.name}/{shot['label']} draws where the panel cannot show it",
        )


if __name__ == "__main__":
  unittest.main()
