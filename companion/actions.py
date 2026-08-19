"""Side-effect boundary for capture files and macOS Shortcuts."""

from __future__ import annotations

from datetime import datetime
import logging
import subprocess
import threading
from typing import Callable

from .capture import CaptureRecord, append_capture
from .config import CompanionConfig


LOGGER = logging.getLogger(__name__)
SHORTCUTS = "/usr/bin/shortcuts"


def run_shortcut(name: str, *, timeout: float = 30.0) -> bool:
  """Launch one allowlisted Shortcut and reap it away from the serial loop."""

  try:
    process = subprocess.Popen(
      [SHORTCUTS, "run", name],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      stdin=subprocess.DEVNULL,
      shell=False,
      start_new_session=True,
    )
  except OSError as error:
    LOGGER.error("Shortcut %r failed to start: %s", name, error)
    return False

  def reap() -> None:
    try:
      return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
      LOGGER.error("Shortcut %r exceeded %.0f seconds; terminating launcher", name, timeout)
      process.terminate()
      try:
        process.wait(timeout=1.0)
      except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
      return
    if return_code != 0:
      LOGGER.error("Shortcut %r exited with status %s", name, return_code)

  threading.Thread(target=reap, name="sokkon-shortcut", daemon=True).start()
  return True


class ActionHandler:
  def __init__(
    self,
    config: CompanionConfig,
    *,
    dry_run: bool = False,
    shortcut_runner: Callable[[str], bool] = run_shortcut,
  ) -> None:
    self._config = config
    self._dry_run = dry_run
    self._shortcut_runner = shortcut_runner

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
    try:
      if intent == "CAPTURE":
        if self._dry_run:
          LOGGER.info("dry-run capture: %s %s %s", timestamp.isoformat(), mode, context)
          return False, "DRY_RUN_NOT_SAVED"
        else:
          append_capture(
            self._config.capture_path,
            CaptureRecord(
              timestamp=timestamp,
              mode=mode,
              context=context,
              focus=focus,
              elapsed_ms=elapsed_ms,
            ),
          )

      shortcut_name = self._config.shortcuts.get(intent)
      if shortcut_name:
        if self._dry_run:
          LOGGER.info("dry-run Shortcut: %s", shortcut_name)
          return False, "DRY_RUN_ACTION_SKIPPED"
        elif not self._shortcut_runner(shortcut_name):
          if intent == "CAPTURE":
            LOGGER.error(
              "capture is durable, but optional Shortcut %r failed",
              shortcut_name,
            )
          else:
            return False, "SHORTCUT_FAILED"
      return True, None
    except OSError as error:
      LOGGER.error("event %s failed: %s", intent, error)
      return False, "CAPTURE_WRITE_FAILED" if intent == "CAPTURE" else "ACTION_FAILED"
    except Exception as error:  # Keep malformed external integrations from killing the serial loop.
      LOGGER.error("event %s failed unexpectedly: %s", intent, error)
      return False, "ACTION_FAILED"
