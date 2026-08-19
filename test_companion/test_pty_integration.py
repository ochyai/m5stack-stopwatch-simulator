from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import pty
import select
import tempfile
import unittest

from companion.actions import ActionHandler
from companion.config import CompanionConfig
from companion.serial_io import SerialPort
from companion.service import CompanionSession

DEVICE = "02AABBCCDDEE"
SESSION = "0123456789ABCDEF"


class PtyIntegrationTest(unittest.TestCase):
  def test_event_ack_result_and_capture_over_pty(self) -> None:
    master, original_slave = pty.openpty()
    slave_path = os.ttyname(original_slave)
    os.close(original_slave)
    fixed_time = datetime(2026, 8, 19, 16, 45, tzinfo=timezone(timedelta(hours=9)))

    try:
      with tempfile.TemporaryDirectory() as directory:
        capture_path = Path(directory) / "Sokkon Inbox.md"
        with SerialPort(slave_path) as serial_port:
          os.write(
            master,
            (
              f"SOKKON|PONG|2|{DEVICE}|{SESSION}\n"
              f"EVENT|{DEVICE}|{SESSION}|31|CAPTURE|9000|REST|PAUSED|3723004\n"
            ).encode(),
          )
          session = CompanionSession(
            serial_port,
            ActionHandler(CompanionConfig(capture_path, {})),
            app_getter=lambda: "Preview",
            clock=lambda: fixed_time,
          )
          session.run(once=True)
          output = self._read_available(master).decode("utf-8")

        lines = output.splitlines()
        self.assertEqual(lines[0], "PING")
        self.assertIn("STATE|16:45|READ|Preview|AUTO MODE", lines)
        self.assertLess(
          lines.index(f"ACK|{SESSION}|31|ACCEPTED"),
          lines.index(f"RESULT|{SESSION}|31|OK"),
        )

        capture = capture_path.read_text(encoding="utf-8")
        self.assertIn("2026-08-19T16:45:00+09:00", capture)
        self.assertIn("[REST] MARK — app: Preview", capture)
        self.assertIn("focus: PAUSED 01:02:03.004", capture)
    finally:
      os.close(master)

  @staticmethod
  def _read_available(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
      readable, _, _ = select.select([descriptor], [], [], 0.1)
      if not readable:
        return b"".join(chunks)
      chunk = os.read(descriptor, 4096)
      if not chunk:
        return b"".join(chunks)
      chunks.append(chunk)


if __name__ == "__main__":
  unittest.main()
