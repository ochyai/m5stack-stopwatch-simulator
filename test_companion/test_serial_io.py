from __future__ import annotations

import os
from pathlib import Path
import pty
import select
import tempfile
import termios
import unittest

from companion.serial_io import PortDetectionError, SerialError, SerialPort, detect_port


DEVICE = "02AABBCCDDEE"
SESSION = "0123456789ABCDEF"


class SerialPortTest(unittest.TestCase):
  def test_pty_round_trip_and_baud(self) -> None:
    master, original_slave = pty.openpty()
    slave_path = os.ttyname(original_slave)
    os.close(original_slave)
    try:
      with SerialPort(slave_path) as serial_port:
        attributes = termios.tcgetattr(serial_port.fileno())
        self.assertEqual(attributes[4], termios.B115200)
        self.assertEqual(attributes[5], termios.B115200)

        serial_port.write_line("PING")
        readable, _, _ = select.select([master], [], [], 1.0)
        self.assertTrue(readable)
        self.assertEqual(os.read(master, 64), b"PING\n")

        os.write(
          master,
          (
            f"SOKKON|READY|2|{DEVICE}|{SESSION}\r\n"
            f"EVENT|{DEVICE}|{SESSION}|9|CAPTURE|123|BUILD|RUNNING|456\n"
          ).encode(),
        )
        self.assertEqual(
          serial_port.read_lines(timeout=1.0),
          [
            f"SOKKON|READY|2|{DEVICE}|{SESSION}",
            f"EVENT|{DEVICE}|{SESSION}|9|CAPTURE|123|BUILD|RUNNING|456",
          ],
        )
    finally:
      os.close(master)

  def test_open_preserves_device_ready_already_in_receive_queue(self) -> None:
    master, original_slave = pty.openpty()
    slave_path = os.ttyname(original_slave)
    try:
      os.write(master, f"SOKKON|READY|2|{DEVICE}|{SESSION}\n".encode())
      with SerialPort(slave_path) as serial_port:
        self.assertEqual(
          serial_port.read_lines(timeout=1.0),
          [f"SOKKON|READY|2|{DEVICE}|{SESSION}"],
        )
    finally:
      os.close(original_slave)
      os.close(master)

  def test_newline_terminated_oversized_frame_is_rejected(self) -> None:
    master, original_slave = pty.openpty()
    slave_path = os.ttyname(original_slave)
    os.close(original_slave)
    try:
      with SerialPort(slave_path, max_buffer=128) as serial_port:
        os.write(master, b"X" * 512 + b"\n")
        with self.assertRaises(SerialError):
          serial_port.read_lines(timeout=1.0)
    finally:
      os.close(master)

  def test_detection_requires_exactly_one_candidate(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      pattern = str(root / "cu.usbmodem*")
      with self.assertRaises(PortDetectionError):
        detect_port(pattern=pattern)

      first = root / "cu.usbmodem1"
      first.touch()
      self.assertEqual(detect_port(pattern=pattern), str(first))

      second = root / "cu.usbmodem2"
      second.touch()
      with self.assertRaises(PortDetectionError):
        detect_port(pattern=pattern)


if __name__ == "__main__":
  unittest.main()
