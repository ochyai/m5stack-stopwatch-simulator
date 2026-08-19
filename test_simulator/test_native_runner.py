"""Black-box acceptance tests for the compiler-driven SOKKON runner.

These tests intentionally talk only through the runner's stdin/stdout protocol.
If production ``main.cpp`` stops compiling, stops drawing a label, or changes a
timer/input branch, the failure is visible here without reproducing that state
machine in Python.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build-simulator.sh"
BINARY = ROOT / ".simulator" / "sokkon-native"


def _all_text(value: object) -> str:
  """Flatten a snapshot for assertions without coupling to draw JSON layout."""
  if isinstance(value, dict):
    return "\n".join(_all_text(item) for item in value.values())
  if isinstance(value, list):
    return "\n".join(_all_text(item) for item in value)
  return str(value)


class NativeRunner:
  def __init__(self) -> None:
    self.process = subprocess.Popen(
      [str(BINARY)],
      cwd=ROOT,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
      bufsize=1,
    )

  def command(self, command: str) -> dict[str, object]:
    assert self.process.stdin is not None
    assert self.process.stdout is not None
    self.process.stdin.write(command + "\n")
    self.process.stdin.flush()
    line = self.process.stdout.readline()
    if not line:
      stderr = ""
      if self.process.stderr is not None:
        stderr = self.process.stderr.read()
      raise AssertionError(
        f"native runner exited with {self.process.poll()}; stderr={stderr!r}"
      )
    try:
      snapshot = json.loads(line)
    except json.JSONDecodeError as error:
      raise AssertionError(f"stdout was not one NDJSON object: {line!r}") from error
    if not isinstance(snapshot, dict):
      raise AssertionError(f"snapshot must be an object, got {type(snapshot).__name__}")
    return snapshot

  def close(self) -> None:
    if self.process.stdin is not None:
      self.process.stdin.close()
    try:
      self.process.wait(timeout=2)
    except subprocess.TimeoutExpired:
      self.process.terminate()
      self.process.wait(timeout=2)
    remainder = ""
    if self.process.stdout is not None:
      remainder = self.process.stdout.read()
      self.process.stdout.close()
    if self.process.stderr is not None:
      self.process.stderr.read()
      self.process.stderr.close()
    if remainder:
      raise AssertionError(f"unsolicited native stdout: {remainder!r}")

  def __enter__(self) -> NativeRunner:
    return self

  def __exit__(self, *_args: object) -> None:
    self.close()


class NativeRunnerAcceptanceTest(unittest.TestCase):
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
    if not BINARY.is_file():
      raise AssertionError(f"build did not create {BINARY}")

  def test_build_compiles_both_unmodified_production_translation_units(self) -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    self.assertIn("firmware/apps/10_sokkon/main.cpp", script)
    self.assertIn("firmware/shared/board.cpp", script)

  def test_initial_snapshot_contains_actual_production_draw_calls(self) -> None:
    with NativeRunner() as runner:
      snapshot = runner.command("SNAPSHOT")

    self.assertEqual(snapshot["frame"]["width"], 466)
    self.assertEqual(snapshot["frame"]["height"], 466)
    self.assertGreater(len(snapshot["frame"]["commands"]), 10)
    frame_text = _all_text(snapshot["frame"])
    for production_label in (
      "NOW",
      "FOCUS / PAUSED",
      "00:00:00.00",
      "MARK",
      "MODE",
      "TOUCH  FOCUS",
      "MARKS 0",
    ):
      self.assertIn(production_label, frame_text)
    self.assertEqual(snapshot["screen"]["mode"], "NOW")
    self.assertFalse(snapshot["screen"]["focus_running"])
    self.assertEqual(snapshot["firmware"]["shell_subtitle"], "LOCAL FIRST INTERFACE")
    self.assertEqual(snapshot["firmware"]["primary_aria"], "現在をマーク")
    self.assertTrue(snapshot["firmware"]["host_controls"])

  def test_mark_ok_runs_event_ack_result_and_updates_production_ui(self) -> None:
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tOUTCOME\tOK")
      runner.command("CONFIGURE\tLATENCY_MS\t0")
      snapshot = runner.command("ACTION\tMARK")

    self.assertEqual(snapshot["screen"]["marks"], 1)
    self.assertEqual(snapshot["screen"]["toast"], "MARK SAVED")
    self.assertFalse(snapshot["pending"])
    text = _all_text(snapshot)
    self.assertIn("EVENT|", text)
    self.assertIn("ACK|", text)
    self.assertIn("RESULT|", text)
    self.assertIn("MARK SAVED", _all_text(snapshot["frame"]))

  def test_mark_error_and_timeout_use_production_result_paths(self) -> None:
    with self.subTest(outcome="ERROR"):
      with NativeRunner() as runner:
        runner.command("CONFIGURE\tOUTCOME\tERROR")
        runner.command("CONFIGURE\tLATENCY_MS\t0")
        failed = runner.command("ACTION\tMARK")
      self.assertEqual(failed["screen"]["toast"], "MAC ERROR")
      self.assertEqual(failed["screen"]["marks"], 0)
      self.assertFalse(failed["pending"])
      self.assertIn("MAC ERROR", _all_text(failed["frame"]))

    with self.subTest(outcome="TIMEOUT"):
      with NativeRunner() as runner:
        runner.command("CONFIGURE\tOUTCOME\tTIMEOUT")
        waiting = runner.command("ACTION\tMARK")
        timed_out = runner.command("ADVANCE\t30001")
      self.assertTrue(waiting["pending"])
      self.assertEqual(timed_out["screen"]["toast"], "SAVE UNKNOWN")
      self.assertFalse(timed_out["pending"])
      self.assertIn("SAVE UNKNOWN", _all_text(timed_out["frame"]))

  def test_ok_result_due_before_large_advance_beats_production_timeout(self) -> None:
    """ADVANCE must pump an early RESULT before crossing the 30 s deadline."""
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tOUTCOME\tOK")
      runner.command("CONFIGURE\tLATENCY_MS\t400")
      waiting = runner.command("ACTION\tMARK")
      advanced = runner.command("ADVANCE\t30001")

    self.assertEqual(waiting["screen"]["marks"], 0)
    self.assertTrue(waiting["pending"])
    self.assertEqual(advanced["screen"]["marks"], 1)
    self.assertFalse(advanced["pending"])
    self.assertNotEqual(advanced["screen"]["toast"], "SAVE UNKNOWN")

  def test_disconnect_drops_an_already_scheduled_host_result(self) -> None:
    """A cable/host disconnect must not deliver a queued ACK or RESULT later."""
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tOUTCOME\tOK")
      runner.command("CONFIGURE\tLATENCY_MS\t10000")
      waiting = runner.command("ACTION\tMARK")
      runner.command("CONFIGURE\tCONNECTED\t0")
      offline = runner.command("ADVANCE\t11000")

    self.assertTrue(waiting["pending"])
    self.assertFalse(offline["scenario"]["connected"])
    self.assertFalse(offline["screen"]["connected"])
    self.assertEqual(offline["screen"]["marks"], 0)
    self.assertTrue(offline["pending"])
    self.assertNotEqual(offline["screen"]["toast"], "MARK SAVED")

  def test_accelerated_wall_clock_times_out_before_a_late_result(self) -> None:
    """Real-time scaling must preserve the production timeout/result order."""
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tTIME_SCALE\t1000")
      runner.command("CONFIGURE\tOUTCOME\tOK")
      runner.command("CONFIGURE\tLATENCY_MS\t40000")
      waiting = runner.command("ACTION\tMARK")
      time.sleep(0.055)
      timed_out = runner.command("SNAPSHOT")

    self.assertTrue(waiting["pending"])
    self.assertEqual(timed_out["screen"]["marks"], 0)
    self.assertFalse(timed_out["pending"])
    # At roughly 55 virtual seconds the 1.6 s SAVE UNKNOWN toast has expired,
    # but the production timeout's three-pulse, intensity-95 pattern remains
    # observable and the late OK must not increment MARKS.
    self.assertNotEqual(timed_out["screen"]["toast"], "MARK SAVED")
    self.assertEqual(timed_out["haptic"]["intensity"], 95)
    self.assertGreaterEqual(timed_out["haptic"]["pulses"], 4)

  def test_mode_and_focus_actions_execute_the_production_branches(self) -> None:
    with NativeRunner() as runner:
      mode = runner.command("ACTION\tMODE")
      focus = runner.command("ACTION\tFOCUS")
      elapsed = runner.command("ADVANCE\t1234")

    self.assertEqual(mode["screen"]["mode"], "BUILD")
    self.assertIn("BUILD", _all_text(mode["frame"]))
    self.assertTrue(focus["screen"]["focus_running"])
    self.assertIn("FOCUS START", _all_text(focus["frame"]))
    self.assertGreaterEqual(elapsed["screen"]["elapsed_ms"], 1234)
    self.assertIn("FOCUS / RUNNING", _all_text(elapsed["frame"]))

  def test_host_state_and_power_hal_flow_through_production_parsers(self) -> None:
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tCONTEXT\tCODEX SESSION")
      runner.command("CONFIGURE\tDETAIL\tCOMPILER DRIVEN")
      runner.command("CONFIGURE\tHOST_MODE\tMEET")
      runner.command("CONFIGURE\tBATTERY_PERCENT\t73")
      runner.command("CONFIGURE\tCHARGING\t1")
      snapshot = runner.command("ADVANCE\t1001")

    self.assertEqual(snapshot["screen"]["mode"], "MEET")
    self.assertEqual(snapshot["screen"]["context"], "CODEX SESSION")
    self.assertEqual(snapshot["screen"]["detail"], "COMPILER DRIVEN")
    self.assertEqual(snapshot["screen"]["battery_percent"], 73)
    self.assertTrue(snapshot["screen"]["charging"])
    frame_text = _all_text(snapshot["frame"])
    self.assertIn("MEET", frame_text)
    self.assertIn("CODEX SESSION", frame_text)
    self.assertIn("COMPILER DRIVEN", frame_text)
    self.assertIn("BAT 73%+", frame_text)

  def test_host_disconnect_uses_real_five_second_guard(self) -> None:
    with NativeRunner() as runner:
      runner.command("CONFIGURE\tCONNECTED\t0")
      runner.command("ADVANCE\t6001")
      snapshot = runner.command("ACTION\tMARK")

    self.assertFalse(snapshot["screen"]["connected"])
    self.assertEqual(snapshot["screen"]["marks"], 0)
    self.assertEqual(snapshot["screen"]["toast"], "NOT SAVED")
    self.assertIn("MAC NOT CONNECTED", _all_text(snapshot["frame"]))

  def test_production_dim_sleep_and_wake_timers(self) -> None:
    with NativeRunner() as runner:
      dimmed = runner.command("ADVANCE\t120001")
      sleeping = runner.command("ADVANCE\t600001")
      awake = runner.command("ACTION\tWAKE")

    self.assertEqual(dimmed["frame"]["brightness"], 20)
    self.assertFalse(dimmed["screen"]["sleeping"])
    self.assertEqual(sleeping["frame"]["brightness"], 0)
    self.assertTrue(sleeping["screen"]["sleeping"])
    self.assertEqual(awake["frame"]["brightness"], 96)
    self.assertFalse(awake["screen"]["sleeping"])
    self.assertFalse(awake["screen"]["focus_running"])

  def test_each_command_emits_exactly_one_json_object_line(self) -> None:
    commands = "SNAPSHOT\nACTION\tMODE\nADVANCE\t101\n"
    result = subprocess.run(
      [str(BINARY)],
      cwd=ROOT,
      input=commands,
      text=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=5,
      check=True,
    )
    lines = result.stdout.splitlines()
    self.assertEqual(len(lines), 3, result.stdout)
    snapshots = [json.loads(line) for line in lines]
    self.assertTrue(all(isinstance(snapshot, dict) for snapshot in snapshots))
    revisions = [snapshot["revision"] for snapshot in snapshots]
    self.assertTrue(all(isinstance(revision, int) for revision in revisions))
    self.assertEqual(revisions[1:], [revisions[0] + 1, revisions[0] + 2])


if __name__ == "__main__":
  unittest.main()
