"""Process bridge to the compiler-driven SOKKON native simulator.

The Python layer deliberately owns no device state-machine semantics.  It sends
strict, tab-delimited commands to the native executable and accepts exactly one
NDJSON snapshot for each command.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import math
import os
from pathlib import Path
import selectors
import subprocess
import threading
import time
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BINARY = REPOSITORY_ROOT / ".simulator" / "sokkon-native"
DEFAULT_BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build-simulator.sh"

ACTION_COMMANDS = {
  "mark": "MARK",
  "mode": "MODE",
  "focus": "FOCUS",
  "wake": "WAKE",
}
ADVANCE_COMMANDS = {
  "advance_6s": 6_001,
  "advance_30s": 30_001,
  "advance_2m": 120_001,
  "advance_10m": 600_001,
}
SUPPORTED_ACTIONS = frozenset((*ACTION_COMMANDS, *ADVANCE_COMMANDS, "reset"))
CONFIGURATION_KEYS = (
  "connected",
  "outcome",
  "latency_ms",
  "context",
  "detail",
  "host_mode",
  "battery_percent",
  "charging",
  "time_scale",
)
MODE_ORDER = ("NOW", "BUILD", "READ", "MEET", "PRESENT", "REST")


class BackendError(RuntimeError):
  """Base class for native simulator failures."""


class BackendInputError(BackendError, ValueError):
  """A caller supplied an unsupported action or scenario value."""


class BackendBuildError(BackendError):
  """The native simulator could not be built."""


class BackendProcessError(BackendError):
  """The native child exited or could not be started."""


class BackendProtocolError(BackendError):
  """The child emitted invalid protocol output."""


class BackendTimeoutError(BackendError, TimeoutError):
  """The child failed to answer within the command deadline."""


def normalize_action(action: object) -> str:
  """Return a canonical, allowlisted simulator action."""
  if not isinstance(action, str):
    raise BackendInputError("action must be a string")
  normalized = action.strip().lower()
  if normalized not in SUPPORTED_ACTIONS:
    expected = ", ".join(sorted(SUPPORTED_ACTIONS))
    raise BackendInputError(f"unsupported action; expected one of: {expected}")
  return normalized


def normalize_configuration(mapping: object) -> dict[str, str]:
  """Validate scenario values and encode their wire representations."""
  if not isinstance(mapping, Mapping):
    raise BackendInputError("scenario must be a JSON object")
  unknown = set(mapping) - set(CONFIGURATION_KEYS)
  if unknown:
    names = ", ".join(sorted(str(key) for key in unknown))
    raise BackendInputError(f"unknown scenario field(s): {names}")

  encoded: dict[str, str] = {}
  for key in CONFIGURATION_KEYS:
    if key not in mapping:
      continue
    value = mapping[key]
    if key in ("connected", "charging"):
      if type(value) is not bool:
        raise BackendInputError(f"{key} must be a boolean")
      encoded[key] = "1" if value else "0"
    elif key == "outcome":
      if not isinstance(value, str) or value.upper() not in ("OK", "ERROR", "TIMEOUT"):
        raise BackendInputError("outcome must be OK, ERROR, or TIMEOUT")
      encoded[key] = value.upper()
    elif key == "latency_ms":
      if type(value) is not int or not 0 <= value <= 60_000:
        raise BackendInputError("latency_ms must be an integer from 0 to 60000")
      encoded[key] = str(value)
    elif key in ("context", "detail"):
      if not isinstance(value, str):
        raise BackendInputError(f"{key} must be a string")
      if any(character in value for character in ("\0", "\r", "\n", "\t")):
        raise BackendInputError(f"{key} cannot contain control separators")
      maximum = 256 if key == "context" else 512
      if len(value.encode("utf-8")) > maximum:
        raise BackendInputError(f"{key} exceeds {maximum} UTF-8 bytes")
      encoded[key] = value
    elif key == "host_mode":
      if not isinstance(value, str) or value.upper() not in MODE_ORDER:
        raise BackendInputError(f"host_mode must be one of: {', '.join(MODE_ORDER)}")
      encoded[key] = value.upper()
    elif key == "battery_percent":
      if type(value) is not int or not 0 <= value <= 100:
        raise BackendInputError("battery_percent must be an integer from 0 to 100")
      encoded[key] = str(value)
    elif key == "time_scale":
      if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BackendInputError("time_scale must be a finite number")
      numeric = float(value)
      if not math.isfinite(numeric) or not 0.01 <= numeric <= 1_000:
        raise BackendInputError("time_scale must be between 0.01 and 1000")
      encoded[key] = format(numeric, ".15g")
  return encoded


def native_sources(repository_root: Path = REPOSITORY_ROOT) -> tuple[Path, ...]:
  """Return source files whose modification makes the native binary stale."""
  candidates: list[Path] = [
    repository_root / "scripts" / "build-simulator.sh",
    repository_root / "firmware" / "apps" / "10_sokkon" / "main.cpp",
  ]
  for directory in (
    repository_root / "simulator" / "native",
    repository_root / "firmware" / "shared",
  ):
    if directory.is_dir():
      candidates.extend(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in (".c", ".cc", ".cpp", ".h", ".hh", ".hpp")
      )
  return tuple(candidates)


def binary_is_stale(binary: Path, sources: Iterable[Path]) -> bool:
  """Return true when the binary is absent or older than an input."""
  try:
    binary_mtime = binary.stat().st_mtime_ns
  except FileNotFoundError:
    return True
  return any(
    source.is_file() and source.stat().st_mtime_ns > binary_mtime
    for source in sources
  )


def ensure_native_binary(
  binary: Path = DEFAULT_BINARY,
  build_script: Path = DEFAULT_BUILD_SCRIPT,
  *,
  sources: Iterable[Path] | None = None,
  repository_root: Path = REPOSITORY_ROOT,
  timeout: float = 120.0,
) -> None:
  """Build the native simulator when its executable is missing or stale."""
  source_files = tuple(sources) if sources is not None else native_sources(repository_root)
  if binary_is_stale(binary, source_files):
    if not build_script.is_file():
      raise BackendBuildError(f"native build script not found: {build_script}")
    try:
      result = subprocess.run(
        [str(build_script)],
        cwd=repository_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
      )
    except (OSError, subprocess.TimeoutExpired) as error:
      raise BackendBuildError(f"native simulator build failed: {error}") from error
    if result.returncode != 0:
      output = result.stdout.decode("utf-8", "replace")[-4_096:].strip()
      suffix = f": {output}" if output else ""
      raise BackendBuildError(
        f"native simulator build exited with status {result.returncode}{suffix}"
      )

  if not binary.is_file():
    raise BackendBuildError(f"native simulator binary was not produced: {binary}")
  if not os.access(binary, os.X_OK):
    raise BackendBuildError(f"native simulator binary is not executable: {binary}")


class NativeSimulatorBackend:
  """Thread-safe request/response bridge to the native simulator process."""

  def __init__(
    self,
    binary_path: str | os.PathLike[str] | None = None,
    *,
    build_script: str | os.PathLike[str] | None = None,
    repository_root: str | os.PathLike[str] = REPOSITORY_ROOT,
    source_paths: Iterable[str | os.PathLike[str]] | None = None,
    auto_build: bool | None = None,
    command_timeout: float = 3.0,
    build_timeout: float = 120.0,
    max_line_bytes: int = 4 * 1024 * 1024,
  ) -> None:
    explicit_binary = binary_path is not None
    self.binary_path = Path(binary_path) if explicit_binary else DEFAULT_BINARY
    self.build_script = Path(build_script) if build_script is not None else DEFAULT_BUILD_SCRIPT
    self.repository_root = Path(repository_root)
    self.source_paths = (
      tuple(Path(path) for path in source_paths)
      if source_paths is not None
      else native_sources(self.repository_root)
    )
    self.auto_build = (not explicit_binary) if auto_build is None else auto_build
    if command_timeout <= 0:
      raise ValueError("command_timeout must be positive")
    if max_line_bytes < 128:
      raise ValueError("max_line_bytes must be at least 128")
    self.command_timeout = command_timeout
    self.build_timeout = build_timeout
    self.max_line_bytes = max_line_bytes

    self._lock = threading.RLock()
    self._stderr_lock = threading.Lock()
    self._stderr_tail = bytearray()
    self._stdout_buffer = bytearray()
    self._process: subprocess.Popen[bytes] | None = None
    self._closed = False
    self._broken: str | None = None
    with self._lock:
      self._start_locked()

  def __enter__(self) -> NativeSimulatorBackend:
    return self

  def __exit__(self, *_args: object) -> None:
    self.close()

  def snapshot(self) -> dict[str, Any]:
    with self._lock:
      return self._exchange_locked("SNAPSHOT")

  def perform_action(self, action: object) -> dict[str, Any]:
    normalized = normalize_action(action)
    if normalized == "reset":
      return self.reset()
    if normalized in ADVANCE_COMMANDS:
      command = f"ADVANCE\t{ADVANCE_COMMANDS[normalized]}"
    else:
      command = f"ACTION\t{ACTION_COMMANDS[normalized]}"
    with self._lock:
      return self._exchange_locked(command)

  def configure(self, mapping: object) -> dict[str, Any]:
    configuration = normalize_configuration(mapping)
    with self._lock:
      if not configuration:
        return self._exchange_locked("SNAPSHOT")
      snapshot: dict[str, Any] | None = None
      for key, value in configuration.items():
        snapshot = self._exchange_locked(f"CONFIGURE\t{key.upper()}\t{value}")
      assert snapshot is not None
      return snapshot

  def reset(self) -> dict[str, Any]:
    """Restart the executable, restoring its compiled initial state."""
    with self._lock:
      self._require_open_locked()
      self._terminate_locked()
      self._broken = None
      self._start_locked()
      return self._exchange_locked("SNAPSHOT")

  def close(self) -> None:
    with self._lock:
      if self._closed:
        return
      self._closed = True
      self._terminate_locked()

  def _require_open_locked(self) -> None:
    if self._closed:
      raise BackendProcessError("native simulator backend is closed")

  def _start_locked(self) -> None:
    self._require_open_locked()
    if self.auto_build:
      ensure_native_binary(
        self.binary_path,
        self.build_script,
        sources=self.source_paths,
        repository_root=self.repository_root,
        timeout=self.build_timeout,
      )
    elif not self.binary_path.is_file() or not os.access(self.binary_path, os.X_OK):
      raise BackendProcessError(f"native simulator binary is not executable: {self.binary_path}")

    self._stdout_buffer.clear()
    with self._stderr_lock:
      self._stderr_tail.clear()
    try:
      self._process = subprocess.Popen(
        [str(self.binary_path)],
        cwd=self.repository_root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
      )
    except OSError as error:
      self._process = None
      raise BackendProcessError(f"could not start native simulator: {error}") from error

    assert self._process.stderr is not None
    threading.Thread(
      target=self._drain_stderr,
      args=(self._process, self._process.stderr),
      name="sokkon-native-stderr",
      daemon=True,
    ).start()

  def _drain_stderr(self, process: subprocess.Popen[bytes], pipe: Any) -> None:
    try:
      while True:
        chunk = pipe.read(4_096)
        if not chunk:
          return
        with self._stderr_lock:
          self._stderr_tail.extend(chunk)
          if len(self._stderr_tail) > 16_384:
            del self._stderr_tail[:-16_384]
    except OSError:
      return
    finally:
      if self._process is process:
        try:
          pipe.close()
        except OSError:
          pass

  def _stderr_summary(self) -> str:
    with self._stderr_lock:
      text = bytes(self._stderr_tail).decode("utf-8", "replace").strip()
    return text[-2_048:]

  def _exchange_locked(self, command: str) -> dict[str, Any]:
    self._require_open_locked()
    if self._broken is not None:
      raise BackendProcessError(
        f"native simulator requires reset after protocol failure: {self._broken}"
      )
    process = self._process
    if process is None or process.poll() is not None:
      status = None if process is None else process.returncode
      detail = self._stderr_summary()
      suffix = f"; stderr: {detail}" if detail else ""
      raise BackendProcessError(f"native simulator is not running (status {status}){suffix}")
    assert process.stdin is not None
    if "\n" in command or "\r" in command or len(command.encode("utf-8")) > 4_096:
      raise BackendProtocolError("refusing unsafe or oversized native command")

    try:
      process.stdin.write(command.encode("utf-8") + b"\n")
      process.stdin.flush()
      line = self._read_line_locked(process)
      text = line.decode("utf-8")
      snapshot = json.loads(
        text,
        parse_constant=lambda value: (_ for _ in ()).throw(
          ValueError(f"invalid JSON constant {value}")
        ),
      )
      if not isinstance(snapshot, dict):
        raise BackendProtocolError("native response must be a JSON object")
      return snapshot
    except BackendError as error:
      self._break_locked(str(error))
      raise
    except (BrokenPipeError, OSError) as error:
      failure = BackendProcessError(f"native simulator I/O failed: {error}")
      self._break_locked(str(failure))
      raise failure from error
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
      failure = BackendProtocolError(f"invalid native NDJSON response: {error}")
      self._break_locked(str(failure))
      raise failure from error

  def _read_line_locked(self, process: subprocess.Popen[bytes]) -> bytes:
    assert process.stdout is not None
    deadline = time.monotonic() + self.command_timeout
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
      while True:
        newline = self._stdout_buffer.find(b"\n")
        if newline >= 0:
          if newline > self.max_line_bytes:
            raise BackendProtocolError("native response exceeds maximum line size")
          line = bytes(self._stdout_buffer[:newline])
          del self._stdout_buffer[: newline + 1]
          if not line:
            raise BackendProtocolError("native response line is empty")
          return line
        if len(self._stdout_buffer) > self.max_line_bytes:
          raise BackendProtocolError("native response exceeds maximum line size")

        remaining = deadline - time.monotonic()
        if remaining <= 0 or not selector.select(remaining):
          raise BackendTimeoutError(
            f"native simulator did not respond within {self.command_timeout:g}s"
          )
        chunk = os.read(process.stdout.fileno(), 65_536)
        if not chunk:
          detail = self._stderr_summary()
          suffix = f"; stderr: {detail}" if detail else ""
          raise BackendProcessError(
            f"native simulator exited with status {process.poll()}{suffix}"
          )
        self._stdout_buffer.extend(chunk)
    finally:
      selector.close()

  def _break_locked(self, reason: str) -> None:
    self._broken = reason
    self._terminate_locked()

  def _terminate_locked(self) -> None:
    process = self._process
    self._process = None
    self._stdout_buffer.clear()
    if process is None:
      return
    if process.stdin is not None:
      try:
        process.stdin.close()
      except OSError:
        pass
    if process.poll() is None:
      process.terminate()
      try:
        process.wait(timeout=0.5)
      except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1.0)
    for pipe in (process.stdout, process.stderr):
      if pipe is not None:
        try:
          pipe.close()
        except OSError:
          pass
