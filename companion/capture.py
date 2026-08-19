"""Append capture events to a private local Markdown inbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import stat

from .protocol import sanitize_field


@dataclass(frozen=True)
class CaptureRecord:
  timestamp: datetime
  mode: str
  context: str
  focus: str
  elapsed_ms: int


def append_capture(path: Path, record: CaptureRecord) -> str:
  """Append one record, creating the file and its parent only when called."""

  target = path.expanduser()
  target.parent.mkdir(parents=True, exist_ok=True)
  timestamp = record.timestamp.astimezone().isoformat(timespec="seconds")
  mode = sanitize_field(record.mode, max_length=16)
  context = sanitize_field(record.context, max_length=160)
  focus = sanitize_field(record.focus, max_length=16)
  elapsed = _format_elapsed(record.elapsed_ms)
  entry = f"- {timestamp} [{mode}] MARK — app: {context} — focus: {focus} {elapsed}\n"

  flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
  if hasattr(os, "O_CLOEXEC"):
    flags |= os.O_CLOEXEC
  if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
  if hasattr(os, "O_NONBLOCK"):
    flags |= os.O_NONBLOCK
  descriptor = os.open(target, flags, 0o600)
  metadata = os.fstat(descriptor)
  if not stat.S_ISREG(metadata.st_mode):
    os.close(descriptor)
    raise OSError("capture path must be a regular file")
  with os.fdopen(descriptor, "a", encoding="utf-8", newline="\n") as handle:
    if metadata.st_size == 0:
      handle.write("# Sokkon Inbox\n\n")
    handle.write(entry)
    handle.flush()
    os.fsync(handle.fileno())
  return entry


def _format_elapsed(elapsed_ms: int) -> str:
  if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int) or elapsed_ms < 0:
    raise ValueError("elapsed_ms must be a non-negative integer")
  hours, remainder = divmod(elapsed_ms, 3_600_000)
  minutes, remainder = divmod(remainder, 60_000)
  seconds, milliseconds = divmod(remainder, 1_000)
  return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
