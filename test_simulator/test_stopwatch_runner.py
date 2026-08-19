"""Black-box proof that a second production firmware runs in the simulator."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
import unittest

from simulator.backend import NativeSimulatorBackend, NativeSimulatorBackendManager


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "scripts" / "build-simulator.sh"
BINARY = ROOT / ".simulator" / "stopwatch-native"


def run_commands(*commands: str) -> list[dict[str, object]]:
  result = subprocess.run(
    [str(BINARY)],
    cwd=ROOT,
    input="".join(f"{command}\n" for command in commands),
    text=True,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    timeout=10,
    check=True,
  )
  lines = result.stdout.splitlines()
  if len(lines) != len(commands):
    raise AssertionError(
      f"expected {len(commands)} NDJSON responses, got {len(lines)}; "
      f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
  return [json.loads(line) for line in lines]


def frame_text(snapshot: dict[str, object]) -> str:
  frame = snapshot["frame"]
  assert isinstance(frame, dict)
  commands = frame["commands"]
  assert isinstance(commands, list)
  return "\n".join(
    str(command.get("text", ""))
    for command in commands
    if isinstance(command, dict)
  )


class ProductionStopwatchRunnerTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls) -> None:
    result = subprocess.run(
      [str(BUILD_SCRIPT), "--firmware", "99_stopwatch"],
      cwd=ROOT,
      text=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
      timeout=120,
      check=False,
    )
    if result.returncode != 0:
      raise AssertionError(f"stopwatch native build failed:\n{result.stdout}")

  def test_build_uses_the_second_unmodified_production_main(self) -> None:
    self.assertTrue(BINARY.is_file())
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    self.assertIn("firmware/apps/99_stopwatch/main.cpp", script)
    self.assertIn("simulator/native/stopwatch_runner.cpp", script)
    runner_dependencies = Path(f"{BINARY}.runner.d").read_text(encoding="utf-8")
    board_dependencies = Path(f"{BINARY}.board.d").read_text(encoding="utf-8")
    self.assertIn("firmware/shared/helpers.hpp", runner_dependencies)
    self.assertIn("firmware/shared/stopwatch_core.hpp", runner_dependencies)
    self.assertIn("simulator/native/include/esp_timer.h", runner_dependencies)
    self.assertIn("firmware/shared/board.hpp", board_dependencies)

    initial = run_commands("SNAPSHOT")[0]
    firmware = initial["firmware"]
    assert isinstance(firmware, dict)
    self.assertEqual(firmware["id"], "99_stopwatch")
    self.assertEqual(firmware["shell_subtitle"], "NATIVE FIRMWARE")
    self.assertEqual(firmware["primary_aria"], "ストップウォッチを開始または一時停止")
    self.assertFalse(firmware["host_controls"])
    text = frame_text(initial)
    self.assertIn("PAUSED", text)
    self.assertIn("A / TOUCH  start / pause", text)
    self.assertIn("B          reset", text)
    self.assertIn("IMU tilt  X+0.12  Y-0.08", text)
    self.assertNotIn("FOCUS / PAUSED", text)

  def test_a_runs_real_stopwatch_branch_and_b_resets_it(self) -> None:
    started, advanced, reset = run_commands(
      "ACTION\tMARK",
      "ADVANCE\t1234",
      "ACTION\tMODE",
    )
    started_screen = started["screen"]
    advanced_screen = advanced["screen"]
    reset_screen = reset["screen"]
    assert isinstance(started_screen, dict)
    assert isinstance(advanced_screen, dict)
    assert isinstance(reset_screen, dict)
    self.assertTrue(started_screen["focus_running"])
    self.assertGreaterEqual(advanced_screen["elapsed_ms"], 1234)
    self.assertIn("RUNNING", frame_text(advanced))
    frame = advanced["frame"]
    assert isinstance(frame, dict)
    commands = frame["commands"]
    assert isinstance(commands, list)
    self.assertTrue(
      any(isinstance(command, dict) and command.get("op") == "drawArc" for command in commands)
    )
    self.assertFalse(reset_screen["focus_running"])
    self.assertEqual(reset_screen["elapsed_ms"], 0)
    self.assertIn("PAUSED", frame_text(reset))

  def test_touch_power_and_haptics_flow_through_production_code(self) -> None:
    touched, configured, settled = run_commands(
      "ACTION\tFOCUS",
      "CONFIGURE\tBATTERY_PERCENT\t37",
      "ADVANCE\t100",
    )
    touched_screen = touched["screen"]
    configured_screen = configured["screen"]
    assert isinstance(touched_screen, dict)
    assert isinstance(configured_screen, dict)
    self.assertTrue(touched_screen["focus_running"])
    haptic = touched["haptic"]
    assert isinstance(haptic, dict)
    self.assertGreaterEqual(haptic["pulses"], 1)
    self.assertEqual(configured_screen["battery_percent"], 37)
    self.assertIn("BAT 37%", frame_text(configured))
    settled_haptic = settled["haptic"]
    assert isinstance(settled_haptic, dict)
    self.assertFalse(settled_haptic["active"])
    self.assertEqual(settled_haptic["label"], "IDLE")

  def test_scenario_configuration_does_not_advance_a_running_stopwatch(self) -> None:
    snapshots = run_commands(
      "ACTION\tMARK",
      "CONFIGURE\tCONNECTED\t1",
      "CONFIGURE\tOUTCOME\tOK",
      "CONFIGURE\tLATENCY_MS\t400",
      "CONFIGURE\tCONTEXT\tSTOPWATCH",
      "CONFIGURE\tDETAIL\tPRODUCTION C++",
      "CONFIGURE\tHOST_MODE\tNOW",
      "CONFIGURE\tBATTERY_PERCENT\t84",
      "CONFIGURE\tCHARGING\t0",
    )
    first_screen = snapshots[0]["screen"]
    final_screen = snapshots[-1]["screen"]
    final_scenario = snapshots[-1]["scenario"]
    assert isinstance(first_screen, dict)
    assert isinstance(final_screen, dict)
    assert isinstance(final_scenario, dict)
    self.assertLess(final_screen["elapsed_ms"] - first_screen["elapsed_ms"], 50)
    self.assertFalse(final_screen["connected"])
    self.assertFalse(final_scenario["connected"])

  def test_touch_can_pause_and_wake_is_not_a_hidden_toggle(self) -> None:
    started, paused, after_time, reset, wake = run_commands(
      "ACTION\tFOCUS",
      "ACTION\tFOCUS",
      "ADVANCE\t1000",
      "ACTION\tMODE",
      "ACTION\tWAKE",
    )
    self.assertTrue(started["screen"]["focus_running"])
    self.assertFalse(paused["screen"]["focus_running"])
    self.assertEqual(after_time["screen"]["elapsed_ms"], paused["screen"]["elapsed_ms"])
    self.assertEqual(reset["screen"]["elapsed_ms"], 0)
    self.assertFalse(wake["screen"]["focus_running"])

    running, after_wake = run_commands("ACTION\tMARK", "ACTION\tWAKE")
    self.assertTrue(after_wake["screen"]["focus_running"])
    self.assertLess(after_wake["screen"]["elapsed_ms"] - running["screen"]["elapsed_ms"], 10)

  def test_long_wall_clock_interval_is_applied_before_a_state_change(self) -> None:
    def exercise(start_before_wait: bool) -> dict[str, object]:
      with subprocess.Popen(
        [str(BINARY)],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
      ) as process:
        assert process.stdin is not None
        assert process.stdout is not None

        def command(value: str) -> dict[str, object]:
          process.stdin.write(value + "\n")
          process.stdin.flush()
          return json.loads(process.stdout.readline())

        command("CONFIGURE\tTIME_SCALE\t1000")
        if start_before_wait:
          command("ACTION\tMARK")
        time.sleep(0.62)
        return command("ACTION\tMARK")

    started_after_idle = exercise(start_before_wait=False)
    paused_after_running = exercise(start_before_wait=True)
    self.assertTrue(started_after_idle["screen"]["focus_running"])
    self.assertLess(started_after_idle["screen"]["elapsed_ms"], 100)
    self.assertFalse(paused_after_running["screen"]["focus_running"])
    self.assertGreaterEqual(paused_after_running["screen"]["elapsed_ms"], 610_000)

  def test_advance_is_bounded_and_process_stays_usable_after_bad_input(self) -> None:
    rejected, healthy = run_commands("ADVANCE\t600002", "SNAPSHOT")
    self.assertIn("outside range", rejected["command_error"])
    self.assertNotIn("command_error", healthy)

  def test_backend_selects_each_managed_binary_without_artifact_collision(self) -> None:
    observed = []
    for firmware_id in ("10_sokkon", "99_stopwatch", "10_sokkon"):
      with NativeSimulatorBackend(firmware_id=firmware_id) as backend:
        observed.append(backend.snapshot()["firmware"]["id"])
    self.assertEqual(observed, ["10_sokkon", "99_stopwatch", "10_sokkon"])

  def test_manager_switches_between_both_managed_production_binaries(self) -> None:
    with NativeSimulatorBackendManager() as manager:
      observed = [manager.snapshot()["firmware"]["id"]]
      observed.append(manager.switch_firmware("99_stopwatch")["firmware"]["id"])
      observed.append(manager.switch_firmware("10_sokkon")["firmware"]["id"])
      catalog = manager.firmwares()
    self.assertEqual(observed, ["10_sokkon", "99_stopwatch", "10_sokkon"])
    self.assertEqual(catalog["active"], "10_sokkon")

  def test_build_registry_rejects_paths_before_invoking_a_compiler(self) -> None:
    environment = dict(os.environ)
    environment["CXX"] = "/definitely/not/a/compiler"
    for firmware_id in ("../99_stopwatch", "/tmp/main.cpp", "99_stopwatch\n-DINJECT"):
      with self.subTest(firmware_id=firmware_id):
        result = subprocess.run(
          [str(BUILD_SCRIPT), "--firmware", firmware_id],
          cwd=ROOT,
          env=environment,
          text=True,
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          timeout=5,
          check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsupported simulator firmware", result.stderr)
        self.assertNotIn("not/a/compiler", result.stderr)

    make_payload = 'invalid"; printf MAKE_INJECTION; : "'
    dry_run = subprocess.run(
      ["make", "-n", "simulator-build", f"FIRMWARE={make_payload}"],
      cwd=ROOT,
      text=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=5,
      check=False,
    )
    self.assertIn('--firmware "unsupported"', dry_run.stdout)
    self.assertNotIn("MAKE_INJECTION", dry_run.stdout)

    overridden = subprocess.run(
      [
        "make",
        "-n",
        "simulator-build",
        "FIRMWARE=99_stopwatch",
        f"SIMULATOR_FIRMWARE={make_payload}",
      ],
      cwd=ROOT,
      text=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=5,
      check=False,
    )
    self.assertIn('--firmware "99_stopwatch"', overridden.stdout)
    self.assertNotIn("MAKE_INJECTION", overridden.stdout)

    marker = ROOT / ".simulator" / "make-shell-expansion-marker"
    marker.unlink(missing_ok=True)
    shell_value = f"$(shell touch {marker})"
    untrusted_function = subprocess.run(
      ["make", "-n", "simulator-build", f"FIRMWARE={shell_value}"],
      cwd=ROOT,
      text=True,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      timeout=5,
      check=False,
    )
    self.assertIn('--firmware "unsupported"', untrusted_function.stdout)
    self.assertFalse(marker.exists())


if __name__ == "__main__":
  unittest.main()
