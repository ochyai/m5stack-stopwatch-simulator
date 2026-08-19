from __future__ import annotations

import unittest

from companion.protocol import (
  ProtocolError,
  encode_ack,
  encode_result,
  encode_state,
  parse_device_line,
)

DEVICE = "02AABBCCDDEE"
SESSION = "0123456789ABCDEF"


class ProtocolTest(unittest.TestCase):
  def test_state_encoding_sanitizes_delimiters_and_newlines(self) -> None:
    line = encode_state("09:07", "build", "Visual|Studio\nCode", "")
    self.assertEqual(line, "STATE|09:07|BUILD|Visual/Studio Code|-")

  def test_state_rejects_invalid_time_and_mode(self) -> None:
    self.assertEqual(
      encode_state("12:00", "REST", "Mac"),
      "STATE|12:00|REST|Mac|-",
    )
    with self.assertRaises(ProtocolError):
      encode_state("24:00", "BUILD", "Xcode")
    with self.assertRaises(ProtocolError):
      encode_state("12:00", "UNKNOWN", "Finder")

  def test_ready_and_pong_parsing(self) -> None:
    ready = parse_device_line(f"SOKKON|READY|2|{DEVICE}|{SESSION}\r\n")
    self.assertEqual((ready.kind, ready.version), ("ready", 2))
    self.assertEqual((ready.device_id, ready.session_id), (DEVICE, SESSION))
    self.assertEqual(
      parse_device_line(f"SOKKON|PONG|2|{DEVICE.lower()}|{SESSION.lower()}").kind,
      "pong",
    )

  def test_sequenced_event_and_host_responses(self) -> None:
    event = parse_device_line(
      f"EVENT|{DEVICE}|{SESSION}|42|FOCUS_TOGGLE|123456|REST|RUNNING|98765"
    )
    self.assertEqual(event.kind, "event")
    self.assertEqual(event.sequence, 42)
    self.assertEqual(event.intent, "FOCUS_TOGGLE")
    self.assertEqual(event.uptime_ms, 123456)
    self.assertEqual(event.mode, "REST")
    self.assertEqual(event.focus, "RUNNING")
    self.assertEqual(event.elapsed_ms, 98765)
    self.assertEqual(encode_ack(SESSION, 42), f"ACK|{SESSION}|42|ACCEPTED")
    self.assertEqual(encode_result(SESSION, 42, ok=True), f"RESULT|{SESSION}|42|OK")
    self.assertEqual(
      encode_result(SESSION, 42, ok=False, reason="bad|path\nvalue"),
      f"RESULT|{SESSION}|42|ERROR|bad/path value",
    )

  def test_state_fields_are_bounded_by_utf8_bytes(self) -> None:
    line = encode_state("09:07", "READ", "界" * 96, "文" * 96)
    self.assertLessEqual(len((line + "\n").encode("utf-8")), 256)
    self.assertNotIn("\ufffd", line)

  def test_huge_numeric_field_is_rejected_as_protocol_error(self) -> None:
    line = f"EVENT|{DEVICE}|{SESSION}|{'9' * 5000}|CAPTURE|1|BUILD|PAUSED|0"
    with self.assertRaises(ProtocolError):
      parse_device_line(line)

  def test_event_parser_rejects_unknown_or_invalid_fields(self) -> None:
    for line in (
      f"EVENT|{DEVICE}|{SESSION}|1|SHELL|20|BUILD|RUNNING|10",
      f"EVENT|{DEVICE}|{SESSION}|-1|CAPTURE|20|BUILD|RUNNING|10",
      f"EVENT|{DEVICE}|{SESSION}|1|CAPTURE|-20|BUILD|RUNNING|10",
      f"EVENT|{DEVICE}|{SESSION}|1|CAPTURE|20|UNKNOWN|RUNNING|10",
      f"EVENT|{DEVICE}|{SESSION}|1|CAPTURE|20|BUILD|STOPPED|10",
      f"EVENT|{DEVICE}|{SESSION}|1|CAPTURE|20|BUILD|RUNNING|-10",
      f"EVENT|{DEVICE}|{SESSION}|1|CAPTURE|20",
      "EVENT|CAPTURE",
      f"SOKKON|READY|1|{DEVICE}|{SESSION}",
      f"SOKKON|READY|2|BAD|{SESSION}",
    ):
      with self.subTest(line=line), self.assertRaises(ProtocolError):
        parse_device_line(line)


if __name__ == "__main__":
  unittest.main()
