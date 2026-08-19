"""Small macOS serial transport built only from the Python standard library."""

from __future__ import annotations

import glob
import os
import select
import termios
import time


DEFAULT_PORT_GLOB = "/dev/cu.usbmodem*"


class PortDetectionError(RuntimeError):
  """Raised when a unique USB CDC port cannot be selected safely."""


class SerialError(RuntimeError):
  """Raised for serial open, I/O, or disconnection failures."""


def detect_port(explicit: str | None = None, *, pattern: str = DEFAULT_PORT_GLOB) -> str:
  if explicit:
    candidate = os.path.expanduser(explicit)
    if not os.path.exists(candidate):
      raise PortDetectionError(f"serial port does not exist: {candidate}")
    return candidate

  ports = sorted(port for port in glob.glob(pattern) if os.path.exists(port))
  if not ports:
    raise PortDetectionError(f"no serial port found at {pattern}")
  if len(ports) > 1:
    joined = ", ".join(ports)
    raise PortDetectionError(f"multiple serial ports found; use --port: {joined}")
  return ports[0]


class SerialPort:
  def __init__(self, path: str, *, baud: int = 115200, max_buffer: int = 1024) -> None:
    if baud != 115200:
      raise ValueError("the Sokkon protocol requires 115200 baud")
    self.path = path
    self._fd: int | None = None
    self._original_attributes: list[object] | None = None
    self._buffer = bytearray()
    self._max_buffer = max_buffer

  def __enter__(self) -> "SerialPort":
    self.open()
    return self

  def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
    self.close()

  @property
  def is_open(self) -> bool:
    return self._fd is not None

  def fileno(self) -> int:
    if self._fd is None:
      raise SerialError("serial port is not open")
    return self._fd

  def open(self) -> None:
    if self._fd is not None:
      return
    flags = os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK
    if hasattr(os, "O_CLOEXEC"):
      flags |= os.O_CLOEXEC
    try:
      descriptor = os.open(self.path, flags)
      original = termios.tcgetattr(descriptor)
      attributes = list(original)
      attributes[0] = 0
      attributes[1] = 0
      attributes[2] = termios.CLOCAL | termios.CREAD | termios.CS8
      attributes[3] = 0
      attributes[4] = termios.B115200
      attributes[5] = termios.B115200
      control_chars = list(attributes[6])
      control_chars[termios.VMIN] = 0
      control_chars[termios.VTIME] = 0
      attributes[6] = control_chars
      termios.tcsetattr(descriptor, termios.TCSANOW, attributes)
    except (OSError, termios.error) as error:
      try:
        os.close(descriptor)
      except (UnboundLocalError, OSError):
        pass
      raise SerialError(f"cannot open {self.path}: {error}") from error

    self._fd = descriptor
    self._original_attributes = original

  def close(self) -> None:
    if self._fd is None:
      return
    descriptor = self._fd
    self._fd = None
    try:
      if self._original_attributes is not None:
        termios.tcsetattr(descriptor, termios.TCSANOW, self._original_attributes)
    except (OSError, termios.error):
      pass
    finally:
      self._original_attributes = None
      try:
        os.close(descriptor)
      except OSError:
        pass

  def write_line(self, line: str, *, timeout: float = 2.0) -> None:
    if "\r" in line or "\n" in line:
      raise SerialError("serial lines must not contain embedded newlines")
    payload = (line + "\n").encode("utf-8")
    descriptor = self.fileno()
    deadline = time.monotonic() + timeout
    offset = 0
    while offset < len(payload):
      try:
        written = os.write(descriptor, payload[offset:])
      except BlockingIOError:
        written = 0
      except OSError as error:
        raise SerialError(f"write failed on {self.path}: {error}") from error
      if written:
        offset += written
        continue
      remaining = deadline - time.monotonic()
      if remaining <= 0:
        raise SerialError(f"write timed out on {self.path}")
      _, writable, _ = select.select([], [descriptor], [], remaining)
      if not writable:
        raise SerialError(f"write timed out on {self.path}")

  def read_lines(self, *, timeout: float = 0.25) -> list[str]:
    complete = self._extract_lines()
    if complete:
      if len(self._buffer) > self._max_buffer:
        self._buffer.clear()
        raise SerialError("serial input exceeded the line buffer limit")
      return complete
    if len(self._buffer) > self._max_buffer:
      self._buffer.clear()
      raise SerialError("serial input exceeded the line buffer limit")

    descriptor = self.fileno()
    try:
      readable, _, _ = select.select([descriptor], [], [], max(0.0, timeout))
    except OSError as error:
      raise SerialError(f"select failed on {self.path}: {error}") from error
    if not readable:
      return []

    try:
      chunk = os.read(descriptor, 4096)
    except BlockingIOError:
      return []
    except OSError as error:
      raise SerialError(f"read failed on {self.path}: {error}") from error
    if not chunk:
      raise SerialError(f"serial port disconnected: {self.path}")
    self._buffer.extend(chunk)
    if len(self._buffer) > self._max_buffer and b"\n" not in self._buffer:
      self._buffer.clear()
      raise SerialError("serial input exceeded the line buffer limit")
    return self._extract_lines()

  def _extract_lines(self) -> list[str]:
    lines: list[str] = []
    while True:
      newline = self._buffer.find(b"\n")
      if newline < 0:
        break
      if newline > self._max_buffer:
        del self._buffer[: newline + 1]
        raise SerialError("serial input exceeded the line buffer limit")
      raw = bytes(self._buffer[:newline])
      del self._buffer[: newline + 1]
      line = raw.rstrip(b"\r").decode("utf-8", errors="replace")
      if line:
        lines.append(line)
    return lines
