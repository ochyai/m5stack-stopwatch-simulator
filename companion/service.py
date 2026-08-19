"""Companion session orchestration and duplicate-safe event handling."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
import logging
import time
from typing import Callable

from .actions import ActionHandler
from .app_context import classify_app, frontmost_app_name
from .protocol import (
  PING,
  DeviceMessage,
  ProtocolError,
  encode_ack,
  encode_result,
  encode_state,
  parse_device_line,
  sanitize_field,
)
from .serial_io import SerialPort
from .serial_io import SerialError


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostState:
  timestamp: datetime
  mode: str
  context: str
  detail: str = "-"

  def encode(self) -> str:
    return encode_state(
      self.timestamp.strftime("%H:%M"),
      self.mode,
      self.context,
      self.detail,
    )


@dataclass
class CompanionMemory:
  """State retained while the CLI reconnects to the same device."""

  manual_mode: str | None = None
  device_id: str | None = None
  results: OrderedDict[
    tuple[str, str, int],
    tuple[tuple[object, ...], str],
  ] = field(default_factory=OrderedDict)


class CompanionSession:
  def __init__(
    self,
    serial_port: SerialPort,
    action_handler: ActionHandler,
    *,
    app_getter: Callable[[], str] = frontmost_app_name,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    memory: CompanionMemory | None = None,
    result_cache_size: int = 256,
    expected_device_id: str | None = None,
  ) -> None:
    self._serial = serial_port
    self._actions = action_handler
    self._app_getter = app_getter
    self._clock = clock
    self._last_state_line: str | None = None
    self._memory = memory if memory is not None else CompanionMemory()
    self._result_cache_size = max(1, result_cache_size)
    self._device_id: str | None = None
    self._session_id: str | None = None
    self._expected_device_id = expected_device_id.upper() if expected_device_id else None
    self._queued_lines: list[str] = []

  def run(self, *, once: bool = False, refresh_interval: float = 1.0) -> None:
    self.handshake()
    self.send_state(force=True)
    queued_lines, self._queued_lines = self._queued_lines, []
    for line in queued_lines:
      self.handle_line(line)

    if once:
      deadline = time.monotonic() + 0.35
      while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
          return
        lines = self._serial.read_lines(timeout=remaining)
        if not lines:
          return
        for line in lines:
          self.handle_line(line)

    next_refresh = time.monotonic() + refresh_interval
    while True:
      now = time.monotonic()
      timeout = min(0.25, max(0.0, next_refresh - now))
      for line in self._serial.read_lines(timeout=timeout):
        self.handle_line(line)
      if time.monotonic() >= next_refresh:
        self.send_state(force=True)
        next_refresh = time.monotonic() + refresh_interval

  def handshake(self, *, timeout: float = 2.0) -> tuple[str, str]:
    """Verify protocol identity without sending app context or running actions."""

    self._send(PING)
    self._await_handshake(timeout=timeout)
    assert self._device_id is not None
    assert self._session_id is not None
    return self._device_id, self._session_id

  def _await_handshake(self, *, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while self._session_id is None:
      remaining = deadline - time.monotonic()
      if remaining <= 0:
        raise SerialError("Sokkon v2 handshake timed out; no app context was sent")
      lines = self._serial.read_lines(timeout=min(0.25, remaining))
      for index, line in enumerate(lines):
        LOGGER.debug("device -> host: %s", sanitize_field(line, max_length=160))
        try:
          message = parse_device_line(line)
        except ProtocolError as error:
          LOGGER.warning("ignored pre-handshake device line: %s", error)
          continue
        if message.kind in {"ready", "pong"} and self._accept_identity(message):
          self._queued_lines.extend(lines[index + 1 :])
          return

  def current_state(self) -> HostState:
    timestamp = self._clock()
    app_name = sanitize_field(self._app_getter(), fallback="Mac", max_length=96)
    return HostState(
      timestamp=timestamp,
      mode=self._memory.manual_mode or classify_app(app_name),
      context=app_name,
      detail="MANUAL MODE" if self._memory.manual_mode else "AUTO MODE",
    )

  def send_state(self, *, force: bool = False) -> HostState:
    state = self.current_state()
    line = state.encode()
    if force or line != self._last_state_line:
      self._send(line)
      self._last_state_line = line
    return state

  def handle_line(self, line: str) -> None:
    LOGGER.debug("device -> host: %s", sanitize_field(line, max_length=160))
    try:
      message = parse_device_line(line)
    except ProtocolError as error:
      LOGGER.warning("ignored malformed device line: %s", error)
      return

    if message.kind in {"ready", "pong"}:
      if self._accept_identity(message):
        self.send_state(force=True)
      return
    if message.kind != "event" or message.intent is None:
      return
    if (
      self._device_id is None
      or self._session_id is None
      or message.device_id != self._device_id
      or message.session_id != self._session_id
    ):
      LOGGER.warning("ignored event outside the verified device session")
      return
    assert message.sequence is not None
    assert message.device_id is not None
    assert message.session_id is not None
    cache_key = (message.device_id, message.session_id, message.sequence)
    self._send(encode_ack(message.session_id, message.sequence))
    fingerprint = self._event_fingerprint(message)
    cached = self._memory.results.get(cache_key)
    if cached is not None:
      self._memory.results.move_to_end(cache_key)
      cached_fingerprint, cached_result = cached
      if cached_fingerprint != fingerprint:
        self._send(
          encode_result(
            message.session_id,
            message.sequence,
            ok=False,
            reason="SEQUENCE_CONFLICT",
          )
        )
        return
      self._send(cached_result)
      return

    result = self._execute_event(message)
    self._remember_result(cache_key, fingerprint, result)
    self._send(result)
    self.send_state(force=True)

  def _accept_identity(self, message: DeviceMessage) -> bool:
    if message.device_id is None or message.session_id is None:
      return False
    if (
      self._expected_device_id is not None
      and message.device_id != self._expected_device_id
    ):
      LOGGER.error(
        "refused unpaired Sokkon device %s; expected %s",
        message.device_id,
        self._expected_device_id,
      )
      return False
    trusted_device_id = self._device_id or self._memory.device_id
    if trusted_device_id is not None and message.device_id != trusted_device_id:
      LOGGER.error(
        "refused device identity change from %s to %s",
        trusted_device_id,
        message.device_id,
      )
      return False
    session_changed = message.session_id != self._session_id
    self._device_id = message.device_id
    self._memory.device_id = message.device_id
    self._session_id = message.session_id
    if session_changed:
      LOGGER.info("verified Sokkon device %s session %s", self._device_id, self._session_id)
    return True

  def _execute_event(self, message: DeviceMessage) -> str:
    state = self.current_state()
    assert message.intent is not None
    assert message.sequence is not None
    assert message.session_id is not None
    assert message.mode is not None
    assert message.focus is not None
    assert message.elapsed_ms is not None
    if message.intent == "MODE_NEXT":
      self._memory.manual_mode = message.mode
    ok, reason = self._actions.handle(
      message.intent,
      timestamp=state.timestamp,
      mode=message.mode,
      context=state.context,
      focus=message.focus,
      elapsed_ms=message.elapsed_ms,
    )
    return encode_result(message.session_id, message.sequence, ok=ok, reason=reason)

  @staticmethod
  def _event_fingerprint(message: DeviceMessage) -> tuple[object, ...]:
    return (
      message.intent,
      message.uptime_ms,
      message.mode,
      message.focus,
      message.elapsed_ms,
    )

  def _remember_result(
    self,
    key: tuple[str, str, int],
    fingerprint: tuple[object, ...],
    result: str,
  ) -> None:
    self._memory.results[key] = (fingerprint, result)
    self._memory.results.move_to_end(key)
    while len(self._memory.results) > self._result_cache_size:
      self._memory.results.popitem(last=False)

  def _send(self, line: str) -> None:
    LOGGER.debug("host -> device: %s", line)
    self._serial.write_line(line)
