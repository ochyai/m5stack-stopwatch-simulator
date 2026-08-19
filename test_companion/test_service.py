from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import time
import unittest

from companion.actions import ActionHandler
from companion.config import CompanionConfig
from companion.service import CompanionMemory, CompanionSession


JST = timezone(timedelta(hours=9))
FIXED_TIME = datetime(2026, 8, 19, 15, 30, tzinfo=JST)
DEVICE = "02AABBCCDDEE"
DEVICE_2 = "06AABBCCDDEE"
SESSION = "0123456789ABCDEF"
SESSION_2 = "FEDCBA9876543210"
PONG = f"SOKKON|PONG|2|{DEVICE}|{SESSION}"


def event(
  sequence: int,
  intent: str,
  uptime_ms: int,
  mode: str,
  focus: str,
  elapsed_ms: int,
  *,
  session: str = SESSION,
) -> str:
  return (
    f"EVENT|{DEVICE}|{session}|{sequence}|{intent}|{uptime_ms}|"
    f"{mode}|{focus}|{elapsed_ms}"
  )


class FakeSerial:
  def __init__(self) -> None:
    self.writes: list[str] = []

  def write_line(self, line: str) -> None:
    self.writes.append(line)


class StopSession(Exception):
  pass


class HeartbeatSerial(FakeSerial):
  def __init__(self) -> None:
    super().__init__()
    self.read_count = 0

  def read_lines(self, *, timeout: float) -> list[str]:
    time.sleep(timeout)
    self.read_count += 1
    if self.read_count == 1:
      return [PONG]
    if self.read_count >= 3:
      raise StopSession
    return []


class RecordingActions:
  def __init__(self, serial: FakeSerial, *, result: tuple[bool, str | None] = (True, None)) -> None:
    self.serial = serial
    self.result = result
    self.calls: list[tuple[str, datetime, str, str, str, int]] = []
    self.writes_seen_at_action: list[list[str]] = []

  def handle(
    self,
    intent: str,
    *,
    timestamp: datetime,
    mode: str,
    context: str,
    focus: str,
    elapsed_ms: int,
  ) -> tuple[bool, str | None]:
    self.writes_seen_at_action.append(list(self.serial.writes))
    self.calls.append((intent, timestamp, mode, context, focus, elapsed_ms))
    return self.result


class ServiceTest(unittest.TestCase):
  def make_session(
    self,
    serial: FakeSerial,
    actions: RecordingActions,
  ) -> CompanionSession:
    session = CompanionSession(  # type: ignore[arg-type]
      serial,
      actions,  # type: ignore[arg-type]
      app_getter=lambda: "Visual Studio Code",
      clock=lambda: FIXED_TIME,
    )
    session.handle_line(PONG)
    serial.writes.clear()
    return session

  def test_ack_precedes_action_and_result_follows(self) -> None:
    serial = FakeSerial()
    actions = RecordingActions(serial)
    session = self.make_session(serial, actions)

    session.handle_line(event(7, "CAPTURE", 1000, "REST", "RUNNING", 65432))

    self.assertEqual(
      actions.writes_seen_at_action,
      [[f"ACK|{SESSION}|7|ACCEPTED"]],
    )
    self.assertEqual(len(actions.calls), 1)
    self.assertEqual(actions.calls[0][2:], ("REST", "Visual Studio Code", "RUNNING", 65432))
    self.assertEqual(
      serial.writes[0:2],
      [f"ACK|{SESSION}|7|ACCEPTED", f"RESULT|{SESSION}|7|OK"],
    )
    self.assertEqual(
      serial.writes[2],
      "STATE|15:30|BUILD|Visual Studio Code|AUTO MODE",
    )

  def test_duplicate_sequence_replays_result_without_action(self) -> None:
    serial = FakeSerial()
    actions = RecordingActions(serial)
    session = self.make_session(serial, actions)

    message = event(8, "MODE_NEXT", 1000, "READ", "PAUSED", 0)
    session.handle_line(message)
    first_result = serial.writes[1]
    serial.writes.clear()
    session.handle_line(message)

    self.assertEqual(len(actions.calls), 1)
    self.assertEqual(serial.writes, [f"ACK|{SESSION}|8|ACCEPTED", first_result])

  def test_conflicting_duplicate_is_rejected_without_action(self) -> None:
    serial = FakeSerial()
    actions = RecordingActions(serial)
    session = self.make_session(serial, actions)

    session.handle_line(event(8, "MODE_NEXT", 1000, "READ", "PAUSED", 0))
    serial.writes.clear()
    session.handle_line(event(8, "MODE_NEXT", 1100, "MEET", "PAUSED", 0))

    self.assertEqual(len(actions.calls), 1)
    self.assertEqual(
      serial.writes,
      [
        f"ACK|{SESSION}|8|ACCEPTED",
        f"RESULT|{SESSION}|8|ERROR|SEQUENCE_CONFLICT",
      ],
    )

  def test_duplicate_result_survives_reconnect_session(self) -> None:
    memory = CompanionMemory()
    first_serial = FakeSerial()
    first_actions = RecordingActions(first_serial)
    first_session = CompanionSession(  # type: ignore[arg-type]
      first_serial,
      first_actions,  # type: ignore[arg-type]
      app_getter=lambda: "Xcode",
      clock=lambda: FIXED_TIME,
      memory=memory,
    )
    first_session.handle_line(PONG)
    first_serial.writes.clear()
    message = event(77, "CAPTURE", 1000, "BUILD", "RUNNING", 100)
    first_session.handle_line(message)

    second_serial = FakeSerial()
    second_actions = RecordingActions(second_serial)
    second_session = CompanionSession(  # type: ignore[arg-type]
      second_serial,
      second_actions,  # type: ignore[arg-type]
      app_getter=lambda: "Xcode",
      clock=lambda: FIXED_TIME,
      memory=memory,
    )
    second_session.handle_line(PONG)
    second_serial.writes.clear()
    second_session.handle_line(message)

    self.assertEqual(second_actions.calls, [])
    self.assertEqual(
      second_serial.writes,
      [f"ACK|{SESSION}|77|ACCEPTED", f"RESULT|{SESSION}|77|OK"],
    )

  def test_reboot_session_reuses_sequence_without_old_result(self) -> None:
    memory = CompanionMemory()
    serial = FakeSerial()
    actions = RecordingActions(serial)
    session = CompanionSession(  # type: ignore[arg-type]
      serial,
      actions,  # type: ignore[arg-type]
      app_getter=lambda: "Xcode",
      clock=lambda: FIXED_TIME,
      memory=memory,
    )
    session.handle_line(PONG)
    serial.writes.clear()
    session.handle_line(event(1, "CAPTURE", 1000, "BUILD", "PAUSED", 0))

    session.handle_line(f"SOKKON|PONG|2|{DEVICE}|{SESSION_2}")
    serial.writes.clear()
    session.handle_line(
      event(1, "CAPTURE", 25, "NOW", "PAUSED", 0, session=SESSION_2)
    )

    self.assertEqual(len(actions.calls), 2)
    self.assertEqual(
      serial.writes[:2],
      [f"ACK|{SESSION_2}|1|ACCEPTED", f"RESULT|{SESSION_2}|1|OK"],
    )

  def test_device_identity_change_is_rejected_across_reconnect(self) -> None:
    memory = CompanionMemory()
    first_serial = FakeSerial()
    first_session = CompanionSession(  # type: ignore[arg-type]
      first_serial,
      RecordingActions(first_serial),  # type: ignore[arg-type]
      memory=memory,
      app_getter=lambda: "Xcode",
    )
    first_session.handle_line(PONG)

    second_serial = FakeSerial()
    second_actions = RecordingActions(second_serial)
    second_session = CompanionSession(  # type: ignore[arg-type]
      second_serial,
      second_actions,  # type: ignore[arg-type]
      memory=memory,
      app_getter=lambda: "Xcode",
    )
    with self.assertLogs("companion.service", level="ERROR"):
      second_session.handle_line(f"SOKKON|PONG|2|{DEVICE_2}|{SESSION_2}")
    second_serial.writes.clear()
    with self.assertLogs("companion.service", level="WARNING"):
      second_session.handle_line(
        f"EVENT|{DEVICE_2}|{SESSION_2}|1|CAPTURE|1|NOW|PAUSED|0"
      )

    self.assertEqual(second_actions.calls, [])
    self.assertEqual(second_serial.writes, [])

  def test_persistent_expected_device_rejects_first_mismatch(self) -> None:
    serial = FakeSerial()
    actions = RecordingActions(serial)
    session = CompanionSession(  # type: ignore[arg-type]
      serial,
      actions,  # type: ignore[arg-type]
      app_getter=lambda: "Secret Front App",
      expected_device_id=DEVICE,
    )
    with self.assertLogs("companion.service", level="ERROR"):
      session.handle_line(f"SOKKON|PONG|2|{DEVICE_2}|{SESSION}")

    self.assertEqual(actions.calls, [])
    self.assertEqual(serial.writes, [])

  def test_mode_next_cycles_six_modes_and_overrides_auto_classification(self) -> None:
    serial = FakeSerial()
    actions = RecordingActions(serial)
    app_name = ["Visual Studio Code"]
    session = CompanionSession(  # type: ignore[arg-type]
      serial,
      actions,  # type: ignore[arg-type]
      app_getter=lambda: app_name[0],
      clock=lambda: FIXED_TIME,
    )
    session.handle_line(PONG)
    serial.writes.clear()

    session.handle_line(event(10, "MODE_NEXT", 3000, "READ", "PAUSED", 0))
    self.assertEqual(serial.writes[-1], "STATE|15:30|READ|Visual Studio Code|MANUAL MODE")

    app_name[0] = "Zoom"
    session.send_state(force=True)
    self.assertEqual(serial.writes[-1], "STATE|15:30|READ|Zoom|MANUAL MODE")

    expected_modes = ["MEET", "PRESENT", "REST", "NOW", "BUILD"]
    for sequence, expected_mode in enumerate(expected_modes, start=11):
      session.handle_line(
        event(sequence, "MODE_NEXT", sequence * 1000, expected_mode, "PAUSED", 0)
      )
      self.assertIn(f"STATE|15:30|{expected_mode}|Zoom|MANUAL MODE", serial.writes)

  def test_run_sends_unchanged_state_as_heartbeat(self) -> None:
    serial = HeartbeatSerial()
    actions = RecordingActions(serial)
    session = CompanionSession(  # type: ignore[arg-type]
      serial,
      actions,  # type: ignore[arg-type]
      app_getter=lambda: "Xcode",
      clock=lambda: FIXED_TIME,
    )

    with self.assertRaises(StopSession):
      session.run(refresh_interval=0.01)

    states = [line for line in serial.writes if line.startswith("STATE|")]
    self.assertGreaterEqual(len(states), 2)
    self.assertEqual(len(set(states)), 1)
    self.assertEqual(states[0], "STATE|15:30|BUILD|Xcode|AUTO MODE")

  def test_error_result_is_cached_and_sanitized(self) -> None:
    serial = FakeSerial()
    actions = RecordingActions(serial, result=(False, "bad|capture\npath"))
    session = self.make_session(serial, actions)

    session.handle_line(event(9, "CAPTURE", 2000, "BUILD", "RUNNING", 20))
    self.assertEqual(
      serial.writes[1],
      f"RESULT|{SESSION}|9|ERROR|bad/capture path",
    )

    serial.writes.clear()
    session.handle_line(event(9, "CAPTURE", 2000, "BUILD", "RUNNING", 20))
    self.assertEqual(len(actions.calls), 1)
    self.assertEqual(
      serial.writes,
      [
        f"ACK|{SESSION}|9|ACCEPTED",
        f"RESULT|{SESSION}|9|ERROR|bad/capture path",
      ],
    )

  def test_event_is_ignored_before_verified_handshake(self) -> None:
    serial = FakeSerial()
    actions = RecordingActions(serial)
    session = CompanionSession(  # type: ignore[arg-type]
      serial,
      actions,  # type: ignore[arg-type]
      app_getter=lambda: "Secret Front App",
      clock=lambda: FIXED_TIME,
    )

    with self.assertLogs("companion.service", level="WARNING"):
      session.handle_line(event(1, "CAPTURE", 1000, "BUILD", "PAUSED", 0))

    self.assertEqual(actions.calls, [])
    self.assertEqual(serial.writes, [])

  def test_dry_run_capture_returns_error_and_never_claims_saved(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "Inbox.md"
      serial = FakeSerial()
      actions = ActionHandler(CompanionConfig(target, {}), dry_run=True)
      session = CompanionSession(  # type: ignore[arg-type]
        serial,
        actions,
        app_getter=lambda: "Xcode",
        clock=lambda: FIXED_TIME,
      )
      session.handle_line(PONG)
      serial.writes.clear()

      session.handle_line(event(5, "CAPTURE", 100, "BUILD", "RUNNING", 5000))

      self.assertFalse(target.exists())
      self.assertEqual(serial.writes[0], f"ACK|{SESSION}|5|ACCEPTED")
      self.assertEqual(
        serial.writes[1],
        f"RESULT|{SESSION}|5|ERROR|DRY_RUN_NOT_SAVED",
      )
      self.assertNotIn(f"RESULT|{SESSION}|5|OK", serial.writes)


if __name__ == "__main__":
  unittest.main()
