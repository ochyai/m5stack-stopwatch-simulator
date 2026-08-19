"""Encoding and parsing for the line-oriented Sokkon USB protocol."""

from __future__ import annotations

from dataclasses import dataclass
import re


MODE_ORDER = ("NOW", "BUILD", "READ", "MEET", "PRESENT", "REST")
MODES = frozenset(MODE_ORDER)
INTENTS = frozenset({"CAPTURE", "FOCUS_TOGGLE", "MODE_NEXT"})
PING = "PING"
PROTOCOL_VERSION = 2

_HHMM_PATTERN = re.compile(r"^[0-9]{2}:[0-9]{2}$")
_UNSIGNED_PATTERN = re.compile(r"^[0-9]+$")
_DEVICE_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{12}$")
_SESSION_ID_PATTERN = re.compile(r"^[0-9A-Fa-f]{16}$")
_MAX_SEQUENCE = (1 << 32) - 1
_MAX_UPTIME_MS = (1 << 63) - 1


class ProtocolError(ValueError):
  """Raised when a protocol line is malformed or unsupported."""


@dataclass(frozen=True)
class DeviceMessage:
  kind: str
  intent: str | None = None
  sequence: int | None = None
  uptime_ms: int | None = None
  mode: str | None = None
  focus: str | None = None
  elapsed_ms: int | None = None
  version: int | None = None
  device_id: str | None = None
  session_id: str | None = None


def sanitize_field(value: object, *, fallback: str = "-", max_length: int = 96) -> str:
  """Return one field bounded by UTF-8 bytes that cannot alter a frame."""

  text = str(value).replace("|", "/").replace("\r", " ").replace("\n", " ")
  text = " ".join(text.split())
  if not text:
    text = fallback
  encoded = text.encode("utf-8")
  if len(encoded) <= max_length:
    return text
  return encoded[:max_length].decode("utf-8", errors="ignore") or fallback


def encode_state(hhmm: str, mode: str, context: object, detail: object = "-") -> str:
  if not _HHMM_PATTERN.fullmatch(hhmm):
    raise ProtocolError(f"invalid HH:MM value: {hhmm!r}")
  hour, minute = (int(part) for part in hhmm.split(":"))
  if hour > 23 or minute > 59:
    raise ProtocolError(f"invalid HH:MM value: {hhmm!r}")

  normalized_mode = str(mode).upper()
  if normalized_mode not in MODES:
    raise ProtocolError(f"unsupported mode: {mode!r}")

  return "|".join(
    (
      "STATE",
      hhmm,
      normalized_mode,
      sanitize_field(context),
      sanitize_field(detail),
    )
  )


def encode_ack(session_id: str, sequence: int) -> str:
  return (
    f"ACK|{_validate_session_id(session_id)}|"
    f"{_validate_unsigned(sequence, 'sequence', _MAX_SEQUENCE)}|ACCEPTED"
  )


def encode_result(
  session_id: str,
  sequence: int,
  *,
  ok: bool,
  reason: object | None = None,
) -> str:
  checked_session = _validate_session_id(session_id)
  checked_sequence = _validate_unsigned(sequence, "sequence", _MAX_SEQUENCE)
  if ok:
    return f"RESULT|{checked_session}|{checked_sequence}|OK"
  safe_reason = sanitize_field(reason or "UNKNOWN", max_length=64)
  return f"RESULT|{checked_session}|{checked_sequence}|ERROR|{safe_reason}"


def parse_device_line(line: str) -> DeviceMessage:
  clean_line = line.rstrip("\r\n")
  if "\r" in clean_line or "\n" in clean_line:
    raise ProtocolError("embedded newline in device message")
  parts = clean_line.split("|")
  if (
    len(parts) == 5
    and parts[0] == "SOKKON"
    and parts[1] in {"READY", "PONG"}
    and parts[2] == str(PROTOCOL_VERSION)
  ):
    return DeviceMessage(
      kind=parts[1].lower(),
      version=PROTOCOL_VERSION,
      device_id=_validate_device_id(parts[3]),
      session_id=_validate_session_id(parts[4]),
    )

  if len(parts) == 9 and parts[0] == "EVENT":
    device_id = _validate_device_id(parts[1])
    session_id = _validate_session_id(parts[2])
    sequence = _parse_unsigned(parts[3], "sequence", _MAX_SEQUENCE)
    intent = _validate_intent(parts[4])
    uptime_ms = _parse_unsigned(parts[5], "uptime_ms", _MAX_UPTIME_MS)
    mode = _validate_mode(parts[6])
    focus = _validate_focus(parts[7])
    elapsed_ms = _parse_unsigned(parts[8], "elapsed_ms", _MAX_UPTIME_MS)
    return DeviceMessage(
      kind="event",
      device_id=device_id,
      session_id=session_id,
      intent=intent,
      sequence=sequence,
      uptime_ms=uptime_ms,
      mode=mode,
      focus=focus,
      elapsed_ms=elapsed_ms,
    )

  raise ProtocolError(f"unsupported device message: {sanitize_field(clean_line)!r}")


def _validate_intent(value: str) -> str:
  intent = value.upper()
  if intent not in INTENTS:
    raise ProtocolError(f"unsupported intent: {value!r}")
  return intent


def _validate_mode(value: str) -> str:
  mode = value.upper()
  if mode not in MODES:
    raise ProtocolError(f"unsupported mode: {value!r}")
  return mode


def _validate_focus(value: str) -> str:
  focus = value.upper()
  if focus not in {"RUNNING", "PAUSED"}:
    raise ProtocolError(f"unsupported focus state: {value!r}")
  return focus


def _validate_device_id(value: str) -> str:
  if not _DEVICE_ID_PATTERN.fullmatch(value):
    raise ProtocolError(f"invalid device id: {sanitize_field(value)!r}")
  return value.upper()


def _validate_session_id(value: str) -> str:
  if not _SESSION_ID_PATTERN.fullmatch(value):
    raise ProtocolError(f"invalid session id: {sanitize_field(value)!r}")
  return value.upper()


def _parse_unsigned(value: str, label: str, maximum: int) -> int:
  if len(value) > len(str(maximum)) or not _UNSIGNED_PATTERN.fullmatch(value):
    raise ProtocolError(f"invalid {label}: {value!r}")
  try:
    parsed = int(value)
  except ValueError as error:
    raise ProtocolError(f"invalid {label}: {sanitize_field(value)!r}") from error
  return _validate_unsigned(parsed, label, maximum)


def _validate_unsigned(value: int, label: str, maximum: int) -> int:
  if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
    raise ProtocolError(f"invalid {label}: {value!r}")
  return value
