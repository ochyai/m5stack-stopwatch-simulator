"""JSON configuration loading for host-side capture and Shortcuts actions.

Example::

  {
    "capture_path": "~/Documents/Sokkon Inbox.md",
    "shortcuts": {
      "CAPTURE": "Archive Sokkon Capture",
      "FOCUS_TOGGLE": "Toggle Focus",
      "MODE_NEXT": "Next Sokkon Mode"
    }
  }
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from .protocol import INTENTS


class ConfigError(ValueError):
  """Raised when a companion JSON configuration is invalid."""


@dataclass(frozen=True)
class CompanionConfig:
  capture_path: Path
  shortcuts: Mapping[str, str]


def default_config() -> CompanionConfig:
  return CompanionConfig(
    capture_path=Path.home() / "Documents" / "Sokkon Inbox.md",
    shortcuts={},
  )


def load_config(path: str | Path | None) -> CompanionConfig:
  if path is None:
    return default_config()

  config_path = Path(path).expanduser()
  try:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
  except OSError as error:
    raise ConfigError(f"cannot read config: {error}") from error
  except json.JSONDecodeError as error:
    raise ConfigError(f"invalid JSON at line {error.lineno}, column {error.colno}") from error

  if not isinstance(raw, dict):
    raise ConfigError("config root must be a JSON object")
  unknown_keys = set(raw) - {"capture_path", "shortcuts"}
  if unknown_keys:
    raise ConfigError(f"unknown config keys: {', '.join(sorted(unknown_keys))}")

  capture_value = raw.get("capture_path", "~/Documents/Sokkon Inbox.md")
  if not isinstance(capture_value, str) or not capture_value.strip():
    raise ConfigError("capture_path must be a non-empty string")
  capture_path = Path(capture_value).expanduser()
  if not capture_path.is_absolute():
    capture_path = (config_path.parent / capture_path).resolve()

  shortcuts_value = raw.get("shortcuts", {})
  if not isinstance(shortcuts_value, dict):
    raise ConfigError("shortcuts must be a JSON object")

  shortcuts: dict[str, str] = {}
  for raw_event, shortcut_name in shortcuts_value.items():
    if not isinstance(raw_event, str):
      raise ConfigError("shortcut event names must be strings")
    event = raw_event.upper()
    if event.startswith("EVENT|"):
      event = event.removeprefix("EVENT|")
    if event not in INTENTS:
      raise ConfigError(f"unsupported shortcut event: {raw_event!r}")
    if not isinstance(shortcut_name, str) or not shortcut_name.strip():
      raise ConfigError(f"shortcut for {event} must be a non-empty string")
    shortcut_name = shortcut_name.strip()
    if shortcut_name.startswith("-") or any(char in shortcut_name for char in "\x00\r\n"):
      raise ConfigError(f"unsafe shortcut name for {event}")
    if len(shortcut_name) > 256:
      raise ConfigError(f"shortcut name for {event} is too long")
    shortcuts[event] = shortcut_name

  return CompanionConfig(capture_path=capture_path, shortcuts=shortcuts)
