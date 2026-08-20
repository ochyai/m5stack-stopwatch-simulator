"""Process bridge to the compiler-driven native firmware simulators.

The Python layer deliberately owns no device state-machine semantics.  It sends
strict, tab-delimited commands to the native executable and accepts exactly one
NDJSON snapshot for each command.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import shlex
import signal
import subprocess
import threading
import time
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_SCRIPT = REPOSITORY_ROOT / "scripts" / "build-simulator.sh"


@dataclass(frozen=True)
class FirmwareSpec:
  """Allowlisted production firmware and its native adapter."""

  firmware_id: str
  label: str
  main_source: str
  runner_source: str
  binary_name: str


FIRMWARE_SPECS = {
  "10_sokkon": FirmwareSpec(
    firmware_id="10_sokkon",
    label="SOKKON",
    main_source="firmware/apps/10_sokkon/main.cpp",
    runner_source="simulator/native/runner.cpp",
    binary_name="sokkon-native",
  ),
  "99_stopwatch": FirmwareSpec(
    firmware_id="99_stopwatch",
    label="STOPWATCH",
    main_source="firmware/apps/99_stopwatch/main.cpp",
    runner_source="simulator/native/stopwatch_runner.cpp",
    binary_name="stopwatch-native",
  ),
}
DEFAULT_FIRMWARE_ID = "10_sokkon"
SUPPORTED_FIRMWARE_IDS = tuple(FIRMWARE_SPECS)
DEFAULT_BINARY = REPOSITORY_ROOT / ".simulator" / FIRMWARE_SPECS[DEFAULT_FIRMWARE_ID].binary_name

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
# Scripted sessions may step virtual time freely inside one day; a runner still
# enforces its own firmware-specific ceiling.
MAX_ADVANCE_MS = 24 * 60 * 60 * 1000
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


def firmware_spec(firmware_id: object) -> FirmwareSpec:
  """Resolve a simulator firmware by exact, fixed-registry identifier."""
  if not isinstance(firmware_id, str):
    raise BackendInputError("firmware id must be a string")
  try:
    return FIRMWARE_SPECS[firmware_id]
  except KeyError as error:
    expected = ", ".join(SUPPORTED_FIRMWARE_IDS)
    raise BackendInputError(f"unsupported firmware; expected one of: {expected}") from error


def firmware_catalog(active_firmware_id: object) -> dict[str, Any]:
  """Return public metadata for the fixed simulator firmware registry."""
  active = firmware_spec(active_firmware_id)
  return {
    "active": active.firmware_id,
    "firmwares": [
      {"id": spec.firmware_id, "label": spec.label}
      for spec in FIRMWARE_SPECS.values()
    ],
  }


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


def native_sources(
  repository_root: Path = REPOSITORY_ROOT,
  *,
  firmware_id: str = DEFAULT_FIRMWARE_ID,
) -> tuple[Path, ...]:
  """Return source files whose modification makes the native binary stale."""
  spec = firmware_spec(firmware_id)
  dependency_files = tuple(
    repository_root / ".simulator" / f"{spec.binary_name}.{unit}.d"
    for unit in ("runner", "board")
  )
  candidates: list[Path] = [
    repository_root / "scripts" / "build-simulator.sh",
    repository_root / spec.main_source,
    repository_root / spec.runner_source,
    *dependency_files,
  ]
  for directory in (
    repository_root / "simulator" / "native" / "include",
    repository_root / "firmware" / "shared",
  ):
    if directory.is_dir():
      candidates.extend(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix in (".c", ".cc", ".cpp", ".h", ".hh", ".hpp")
      )
  for dependency_file in dependency_files:
    if not dependency_file.is_file():
      continue
    try:
      dependency_text = dependency_file.read_text(encoding="utf-8")
      logical_lines = dependency_text.replace("\\\n", " ").splitlines()
      for line in logical_lines:
        if not line.strip():
          continue
        dependency_list = line.split(":", 1)[1]
        candidates.extend(Path(value) for value in shlex.split(dependency_list))
    except (IndexError, OSError, ValueError):
      # A malformed dependency manifest must force a rebuild, not silently
      # trust an artifact whose inputs cannot be established.
      candidates.append(repository_root / ".simulator" / ".invalid-dependency-manifest")
  return tuple(candidates)


def binary_is_stale(binary: Path, sources: Iterable[Path]) -> bool:
  """Return true when the binary is absent or older than an input."""
  try:
    binary_mtime = binary.stat().st_mtime_ns
  except FileNotFoundError:
    return True
  for source in sources:
    try:
      source_mtime = source.stat().st_mtime_ns
    except FileNotFoundError:
      return True
    if source_mtime > binary_mtime:
      return True
  return False


def _terminate_build_process_group(process: subprocess.Popen[bytes]) -> None:
  """Boundedly terminate a build and every compiler process it spawned."""
  try:
    try:
      os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
      pass

    try:
      process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
      pass

    # The build-script process may have exited while a compiler that ignored
    # TERM remains in its session. Always address the original process group
    # once more before considering cleanup complete.
    try:
      os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
      pass

    try:
      process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
      process.kill()
      process.wait(timeout=1.0)
  finally:
    for pipe in (process.stdout, process.stderr):
      if pipe is not None:
        try:
          pipe.close()
        except OSError:
          pass


def ensure_native_binary(
  binary: Path = DEFAULT_BINARY,
  build_script: Path = DEFAULT_BUILD_SCRIPT,
  *,
  sources: Iterable[Path] | None = None,
  repository_root: Path = REPOSITORY_ROOT,
  firmware_id: str = DEFAULT_FIRMWARE_ID,
  build_arguments: Iterable[str] = (),
  timeout: float = 120.0,
) -> None:
  """Build the native simulator when its executable is missing or stale.

  ``firmware_id`` selects which inputs make the binary stale.  It is ignored
  when an explicit ``sources`` tuple is supplied.
  """
  source_files = (
    tuple(sources)
    if sources is not None
    else native_sources(repository_root, firmware_id=firmware_id)
  )
  if binary_is_stale(binary, source_files):
    if not build_script.is_file():
      raise BackendBuildError(f"native build script not found: {build_script}")
    try:
      process = subprocess.Popen(
        [str(build_script), *build_arguments],
        cwd=repository_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
      )
    except OSError as error:
      raise BackendBuildError(f"native simulator build failed: {error}") from error

    try:
      output_bytes, _unused_stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
      _terminate_build_process_group(process)
      raise BackendBuildError(
        f"native simulator build timed out after {timeout:g}s"
      ) from error
    except OSError as error:
      _terminate_build_process_group(process)
      raise BackendBuildError(f"native simulator build failed: {error}") from error
    except BaseException:
      _terminate_build_process_group(process)
      raise

    if process.returncode != 0:
      output = output_bytes.decode("utf-8", "replace")[-4_096:].strip()
      suffix = f": {output}" if output else ""
      raise BackendBuildError(
        f"native simulator build exited with status {process.returncode}{suffix}"
      )

  if not binary.is_file():
    raise BackendBuildError(f"native simulator binary was not produced: {binary}")
  if not os.access(binary, os.X_OK):
    raise BackendBuildError(f"native simulator binary is not executable: {binary}")
  if binary_is_stale(binary, source_files):
    raise BackendBuildError("native simulator binary remained stale after build")


class NativeSimulatorBackend:
  """Thread-safe request/response bridge to the native simulator process."""

  def __init__(
    self,
    binary_path: str | os.PathLike[str] | None = None,
    *,
    firmware_id: str = DEFAULT_FIRMWARE_ID,
    build_script: str | os.PathLike[str] | None = None,
    repository_root: str | os.PathLike[str] = REPOSITORY_ROOT,
    source_paths: Iterable[str | os.PathLike[str]] | None = None,
    auto_build: bool | None = None,
    command_timeout: float = 3.0,
    build_timeout: float = 120.0,
    max_line_bytes: int = 4 * 1024 * 1024,
  ) -> None:
    self.firmware = firmware_spec(firmware_id)
    self.firmware_id = self.firmware.firmware_id
    self.repository_root = Path(repository_root).expanduser().resolve()
    explicit_binary = binary_path is not None
    selected_binary = (
      Path(binary_path) if explicit_binary else Path(".simulator") / self.firmware.binary_name
    )
    if not selected_binary.is_absolute():
      selected_binary = self.repository_root / selected_binary
    self.binary_path = selected_binary.resolve()
    selected_build_script = (
      Path(build_script) if build_script is not None else Path("scripts/build-simulator.sh")
    )
    if not selected_build_script.is_absolute():
      selected_build_script = self.repository_root / selected_build_script
    self.build_script = selected_build_script.resolve()
    self.source_paths = (
      tuple(
        path if path.is_absolute() else self.repository_root / path
        for path in (Path(value) for value in source_paths)
      )
      if source_paths is not None
      else native_sources(self.repository_root, firmware_id=self.firmware_id)
    )
    self._verify_firmware_identity = not explicit_binary
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

  def advance(self, milliseconds: object) -> dict[str, Any]:
    """Advance virtual time by an exact number of milliseconds.

    The HTTP API deliberately exposes only the fixed presets in
    ``ADVANCE_COMMANDS``.  This entry point is for scripted sessions, which
    need the same determinism at an arbitrary step.
    """
    if type(milliseconds) is not int or not 0 <= milliseconds <= MAX_ADVANCE_MS:
      raise BackendInputError(
        f"advance must be an integer from 0 to {MAX_ADVANCE_MS} milliseconds"
      )
    with self._lock:
      return self._exchange_locked(f"ADVANCE\t{milliseconds}")

  def freeze_time(self, frozen: object) -> dict[str, Any]:
    """Stop or resume wall-clock time inside the native runner.

    A UI wants a clock that ticks. A scripted session wants virtual time to
    move only when the script says so, which is what makes a replay
    reproducible on any machine.
    """
    if type(frozen) is not bool:
      raise BackendInputError("freeze_time takes a boolean")
    with self._lock:
      return self._exchange_locked(f"FREEZE\t{'1' if frozen else '0'}")

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
        firmware_id=self.firmware_id,
        build_arguments=("--firmware", self.firmware_id),
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
    if self._verify_firmware_identity:
      self._exchange_locked("SNAPSHOT")

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
      if self._verify_firmware_identity:
        firmware = snapshot.get("firmware")
        actual_id = firmware.get("id") if isinstance(firmware, dict) else None
        if actual_id != self.firmware_id:
          raise BackendProtocolError(
            f"native firmware identity mismatch: expected {self.firmware_id}, got {actual_id!r}"
          )
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


class NativeSimulatorBackendManager:
  """Own and transactionally replace one allowlisted native backend.

  The manager is the serialization boundary used by the HTTP server.  A
  replacement is constructed from the fixed firmware registry, started, and
  queried before the current process is closed.  Consequently a build or
  startup failure leaves the current simulator available.
  """

  def __init__(
    self,
    *,
    firmware_id: str = DEFAULT_FIRMWARE_ID,
    backend_factory: Callable[[str], NativeSimulatorBackend] | None = None,
  ) -> None:
    initial_id = firmware_spec(firmware_id).firmware_id
    self._lock = threading.RLock()
    self._closed = False
    self._backend_factory = backend_factory or self._create_native_backend
    self._backend: NativeSimulatorBackend | None = None
    self._active_firmware_id = initial_id
    backend = self._build_backend(initial_id)
    self._backend = backend

  @staticmethod
  def _create_native_backend(firmware_id: str) -> NativeSimulatorBackend:
    # ``firmware_id`` has already been resolved through ``firmware_spec``.
    # NativeSimulatorBackend performs the same exact-registry validation again
    # before selecting any source, binary, or build argument.
    return NativeSimulatorBackend(firmware_id=firmware_id)

  def __enter__(self) -> NativeSimulatorBackendManager:
    return self

  def __exit__(self, *_args: object) -> None:
    self.close()

  @property
  def firmware_id(self) -> str:
    with self._lock:
      self._require_open_locked()
      return self._active_firmware_id

  def firmwares(self) -> dict[str, Any]:
    with self._lock:
      self._require_open_locked()
      return firmware_catalog(self._active_firmware_id)

  def snapshot(self) -> dict[str, Any]:
    with self._lock:
      return self._backend_locked().snapshot()

  def perform_action(self, action: object) -> dict[str, Any]:
    with self._lock:
      return self._backend_locked().perform_action(action)

  def advance(self, milliseconds: object) -> dict[str, Any]:
    with self._lock:
      return self._backend_locked().advance(milliseconds)

  def freeze_time(self, frozen: object) -> dict[str, Any]:
    with self._lock:
      return self._backend_locked().freeze_time(frozen)

  def configure(self, mapping: object) -> dict[str, Any]:
    with self._lock:
      return self._backend_locked().configure(mapping)

  def reset(self) -> dict[str, Any]:
    with self._lock:
      self._require_open_locked()
      return self._replace_backend_locked(self._active_firmware_id)

  def switch_firmware(self, firmware_id: object) -> dict[str, Any]:
    """Switch to an allowlisted firmware and return its first snapshot."""
    target_id = firmware_spec(firmware_id).firmware_id
    with self._lock:
      return self._replace_backend_locked(target_id)

  def close(self) -> None:
    with self._lock:
      if self._closed:
        return
      self._closed = True
      backend = self._backend
      self._backend = None
      if backend is not None:
        backend.close()

  def _backend_locked(self) -> NativeSimulatorBackend:
    self._require_open_locked()
    assert self._backend is not None
    return self._backend

  def _require_open_locked(self) -> None:
    if self._closed:
      raise BackendProcessError("native simulator backend manager is closed")

  def _replace_backend_locked(self, target_id: str) -> dict[str, Any]:
    current = self._backend_locked()
    candidate = self._build_backend(target_id)
    try:
      snapshot = candidate.snapshot()
    except BaseException:
      candidate.close()
      raise

    # The candidate is known-good before the current child is touched. Both
    # close and swap happen while all state/action requests are excluded. This
    # path is shared by firmware selection and reset so a failed rebuild never
    # strands the manager without its previously healthy process.
    try:
      current.close()
    except BaseException:
      candidate.close()
      raise
    self._backend = candidate
    self._active_firmware_id = target_id
    return snapshot

  def _build_backend(self, firmware_id: str) -> NativeSimulatorBackend:
    target_id = firmware_spec(firmware_id).firmware_id
    backend = self._backend_factory(target_id)
    actual_id = getattr(backend, "firmware_id", None)
    if actual_id != target_id:
      try:
        backend.close()
      finally:
        raise BackendProtocolError(
          f"managed backend identity mismatch: expected {target_id}, got {actual_id!r}"
        )
    return backend
