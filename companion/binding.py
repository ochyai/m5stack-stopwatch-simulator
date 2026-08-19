"""Persistent, local device binding for the Sokkon USB trust boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import tempfile


DEFAULT_BINDING_PATH = Path.home() / ".config" / "sokkon" / "device.json"
_DEVICE_ID = re.compile(r"^[0-9A-Fa-f]{12}$")
_MAX_BINDING_BYTES = 1024


class BindingError(ValueError):
  """Raised when a device binding is absent, unsafe, or malformed."""


def normalize_device_id(value: object) -> str:
  if not isinstance(value, str) or not _DEVICE_ID.fullmatch(value):
    raise BindingError("device_id must be exactly 12 hexadecimal characters")
  return value.upper()


def load_binding(path: str | Path | None = None) -> str:
  target = Path(path).expanduser() if path is not None else DEFAULT_BINDING_PATH
  flags = os.O_RDONLY
  if hasattr(os, "O_CLOEXEC"):
    flags |= os.O_CLOEXEC
  if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
  try:
    descriptor = os.open(target, flags)
  except FileNotFoundError as error:
    raise BindingError(f"device binding not found: {target}; run with --pair first") from error
  except OSError as error:
    raise BindingError(f"cannot open device binding {target}: {error}") from error

  try:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
      raise BindingError("device binding must be a regular file")
    if metadata.st_size > _MAX_BINDING_BYTES:
      raise BindingError("device binding is too large")
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
      descriptor = -1
      raw = json.load(handle)
  except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise BindingError(f"invalid device binding {target}: {error}") from error
  finally:
    if descriptor >= 0:
      os.close(descriptor)

  if not isinstance(raw, dict) or set(raw) != {"device_id"}:
    raise BindingError("device binding must contain only device_id")
  return normalize_device_id(raw["device_id"])


def save_binding(
  device_id: str,
  path: str | Path | None = None,
  *,
  replace: bool = False,
) -> Path:
  normalized = normalize_device_id(device_id)
  target = Path(path).expanduser() if path is not None else DEFAULT_BINDING_PATH
  target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

  try:
    current = load_binding(target)
  except BindingError as error:
    if target.exists() or target.is_symlink():
      if not replace:
        raise BindingError(f"refusing to replace existing binding: {error}") from error
    current = None
  if current == normalized:
    return target
  if current is not None and not replace:
    raise BindingError(
      f"binding already trusts {current}; use --replace-binding to trust {normalized}"
    )

  descriptor, temporary_name = tempfile.mkstemp(
    prefix=".device-",
    suffix=".json",
    dir=target.parent,
  )
  temporary = Path(temporary_name)
  try:
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
      descriptor = -1
      json.dump({"device_id": normalized}, handle, sort_keys=True)
      handle.write("\n")
      handle.flush()
      os.fsync(handle.fileno())
    os.replace(temporary, target)
    directory_descriptor = os.open(target.parent, os.O_RDONLY)
    try:
      os.fsync(directory_descriptor)
    finally:
      os.close(directory_descriptor)
  except Exception:
    if descriptor >= 0:
      os.close(descriptor)
    try:
      temporary.unlink()
    except FileNotFoundError:
      pass
    raise
  return target
