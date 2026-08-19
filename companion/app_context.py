"""Read and classify the frontmost macOS application without shell execution."""

from __future__ import annotations

import logging
import subprocess
import unicodedata
from typing import Callable


LOGGER = logging.getLogger(__name__)
FALLBACK_APP = "Mac"
OSASCRIPT = "/usr/bin/osascript"
FRONTMOST_APP_SCRIPT = (
  'ObjC.import("AppKit"); '
  "$.NSWorkspace.sharedWorkspace.frontmostApplication.localizedName.js"
)

_APP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
  (
    "MEET",
    (
      "zoom",
      "zoom.us",
      "microsoft teams",
      "teams",
      "webex",
      "cisco webex meetings",
      "facetime",
      "around",
      "google meet",
      "slack",
    ),
  ),
  (
    "PRESENT",
    (
      "keynote",
      "microsoft powerpoint",
      "powerpoint",
      "libreoffice impress",
      "pitch",
      "mmhmm",
      "obs",
      "obs studio",
    ),
  ),
  (
    "BUILD",
    (
      "xcode",
      "visual studio code",
      "cursor",
      "terminal",
      "ターミナル",
      "iterm2",
      "warp",
      "zed",
      "pycharm",
      "intellij idea",
      "android studio",
      "sublime text",
      "github desktop",
      "docker desktop",
      "touchdesigner",
      "processing",
      "unity",
      "unity hub",
      "arduino ide",
      "ableton live",
      "codex",
      "ollama",
      "chatgpt",
    ),
  ),
  (
    "READ",
    (
      "preview",
      "プレビュー",
      "books",
      "ブック",
      "kindle",
      "adobe acrobat",
      "acrobat reader",
      "skim",
      "safari",
      "google chrome",
      "chrome",
      "firefox",
      "arc",
      "orion",
      "microsoft edge",
    ),
  ),
)


def frontmost_app_name(
  *,
  runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
  timeout: float = 2.0,
) -> str:
  """Return the frontmost app name, or a non-sensitive fallback on any failure."""

  command_runner = runner or subprocess.run
  try:
    completed = command_runner(
      [OSASCRIPT, "-l", "JavaScript", "-e", FRONTMOST_APP_SCRIPT],
      check=False,
      capture_output=True,
      text=True,
      timeout=timeout,
      stdin=subprocess.DEVNULL,
      shell=False,
    )
  except (OSError, subprocess.SubprocessError) as error:
    LOGGER.debug("frontmost app lookup failed: %s", error)
    return FALLBACK_APP

  if completed.returncode != 0:
    LOGGER.debug("frontmost app lookup returned %s", completed.returncode)
    return FALLBACK_APP

  app_name = " ".join(completed.stdout.replace("\r", " ").replace("\n", " ").split())
  return app_name or FALLBACK_APP


def classify_app(app_name: str) -> str:
  """Map a frontmost app to a small, stable Sokkon mode vocabulary."""

  normalized = unicodedata.normalize("NFKC", app_name).casefold().strip()
  for mode, names in _APP_RULES:
    if any(_matches_app(normalized, candidate) for candidate in names):
      return mode
  return "NOW"


def _matches_app(normalized: str, candidate: str) -> bool:
  expected = unicodedata.normalize("NFKC", candidate).casefold()
  if normalized == expected:
    return True
  if not normalized.startswith(expected):
    return False
  suffix = normalized[len(expected) : len(expected) + 1]
  return suffix in {" ", "-", "—", "("}
