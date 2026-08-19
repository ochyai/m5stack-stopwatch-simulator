from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import signal
import tempfile
import textwrap
import threading
import time
import unittest

from simulator.backend import (
  BackendBuildError,
  BackendInputError,
  BackendProcessError,
  BackendProtocolError,
  BackendTimeoutError,
  NativeSimulatorBackend,
  NativeSimulatorBackendManager,
  binary_is_stale,
  ensure_native_binary,
  firmware_catalog,
  firmware_spec,
  native_sources,
  normalize_configuration,
)


ROOT = Path(__file__).resolve().parents[1]


FAKE_NATIVE = r"""
#!/usr/bin/env python3
import json
import os
import sys
import time

mode = os.environ.get("FAKE_NATIVE_MODE", "normal")
state = {"revision": 0, "configuration": {}, "command": "START"}

for raw_line in sys.stdin:
  line = raw_line.rstrip("\n")
  if mode == "timeout":
    time.sleep(2)
    continue
  if mode == "invalid":
    print("not-json", flush=True)
    continue
  if mode == "oversize":
    print(json.dumps({"value": "x" * 1000}), flush=True)
    continue
  parts = line.split("\t", 2)
  state["revision"] += 1
  state["command"] = line
  state["pid"] = os.getpid()
  if parts[0] == "CONFIGURE" and len(parts) == 3:
    state["configuration"][parts[1]] = parts[2]
  print(json.dumps(state, separators=(",", ":")), flush=True)
"""


class NativeBackendTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.directory = Path(self.temporary.name)
    self.binary = self.directory / "fake-native"
    self.binary.write_text(textwrap.dedent(FAKE_NATIVE).lstrip(), encoding="utf-8")
    self.binary.chmod(0o700)

  def tearDown(self) -> None:
    self.temporary.cleanup()

  def backend(self, **kwargs: object) -> NativeSimulatorBackend:
    return NativeSimulatorBackend(
      self.binary,
      repository_root=self.directory,
      auto_build=False,
      **kwargs,
    )

  def hanging_build(self) -> tuple[Path, Path, Path, Path]:
    source = self.directory / "source.cpp"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    binary = self.directory / "not-built"
    pid_file = self.directory / "compiler-descendant.pid"
    build_script = self.directory / "hanging-build.sh"
    build_script.write_text(
      textwrap.dedent(
        """
        #!/bin/sh
        set -eu
        (
          trap '' TERM
          while :; do sleep 10; done
        ) &
        descendant=$!
        printf '%s\n' "${descendant}" > compiler-descendant.pid
        trap '' TERM
        wait "${descendant}"
        """
      ).lstrip(),
      encoding="utf-8",
    )
    build_script.chmod(0o700)
    return binary, source, build_script, pid_file

  def assert_process_exits(self, pid: int) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
      try:
        os.kill(pid, 0)
      except ProcessLookupError:
        return
      time.sleep(0.02)
    self.fail(f"build descendant {pid} survived process-group cleanup")

  def test_snapshot_action_advance_and_configuration_use_strict_commands(self) -> None:
    with self.backend() as backend:
      self.assertEqual(backend.snapshot()["command"], "SNAPSHOT")
      self.assertEqual(backend.perform_action("mark")["command"], "ACTION\tMARK")
      self.assertEqual(
        backend.perform_action("advance_30s")["command"],
        "ADVANCE\t30001",
      )
      snapshot = backend.configure(
        {
          "connected": True,
          "outcome": "timeout",
          "host_mode": "build",
          "time_scale": 4,
        }
      )
    self.assertEqual(
      snapshot["configuration"],
      {
        "CONNECTED": "1",
        "OUTCOME": "TIMEOUT",
        "HOST_MODE": "BUILD",
        "TIME_SCALE": "4",
      },
    )

  def test_reset_restarts_process_and_restores_initial_state(self) -> None:
    with self.backend() as backend:
      before = backend.perform_action("mode")
      reset = backend.reset()
    self.assertNotEqual(before["pid"], reset["pid"])
    self.assertEqual(reset["revision"], 1)
    self.assertEqual(reset["command"], "SNAPSHOT")

  def test_requests_are_serialized_across_threads(self) -> None:
    with self.backend() as backend:
      with ThreadPoolExecutor(max_workers=8) as executor:
        snapshots = list(executor.map(lambda _index: backend.snapshot(), range(24)))
    revisions = sorted(snapshot["revision"] for snapshot in snapshots)
    self.assertEqual(revisions, list(range(1, 25)))

  def test_timeout_breaks_process_until_explicit_reset(self) -> None:
    previous = os.environ.get("FAKE_NATIVE_MODE")
    os.environ["FAKE_NATIVE_MODE"] = "timeout"
    try:
      backend = self.backend(command_timeout=0.05)
      with self.assertRaises(BackendTimeoutError):
        backend.snapshot()
      with self.assertRaises(BackendProcessError):
        backend.snapshot()
      backend.close()
    finally:
      if previous is None:
        os.environ.pop("FAKE_NATIVE_MODE", None)
      else:
        os.environ["FAKE_NATIVE_MODE"] = previous

  def test_invalid_and_oversized_ndjson_are_rejected(self) -> None:
    previous = os.environ.get("FAKE_NATIVE_MODE")
    try:
      for mode, maximum in (("invalid", 4096), ("oversize", 128)):
        os.environ["FAKE_NATIVE_MODE"] = mode
        with self.backend(max_line_bytes=maximum) as backend:
          with self.assertRaises(BackendProtocolError):
            backend.snapshot()
    finally:
      if previous is None:
        os.environ.pop("FAKE_NATIVE_MODE", None)
      else:
        os.environ["FAKE_NATIVE_MODE"] = previous

  def test_configuration_rejects_unknown_types_and_protocol_separators(self) -> None:
    invalid = (
      {"unknown": True},
      {"connected": 1},
      {"latency_ms": True},
      {"context": "one\ttwo"},
      {"battery_percent": 101},
      {"time_scale": float("inf")},
    )
    for mapping in invalid:
      with self.subTest(mapping=mapping), self.assertRaises(BackendInputError):
        normalize_configuration(mapping)

  def test_binary_staleness_uses_nanosecond_mtimes(self) -> None:
    source = self.directory / "source.cpp"
    source.write_text("source", encoding="utf-8")
    self.assertTrue(binary_is_stale(self.directory / "missing", [source]))
    now = time.time_ns()
    os.utime(source, ns=(now, now))
    os.utime(self.binary, ns=(now + 10, now + 10))
    self.assertFalse(binary_is_stale(self.binary, [source]))
    os.utime(source, ns=(now + 20, now + 20))
    self.assertTrue(binary_is_stale(self.binary, [source]))
    self.assertTrue(binary_is_stale(self.binary, [self.directory / "deleted.hpp"]))

  def test_build_timeout_kills_the_compiler_process_group(self) -> None:
    binary, source, build_script, pid_file = self.hanging_build()

    with self.assertRaisesRegex(BackendBuildError, "timed out"):
      ensure_native_binary(
        binary,
        build_script,
        sources=(source,),
        repository_root=self.directory,
        timeout=1.0,
      )

    descendant_pid = int(pid_file.read_text(encoding="utf-8"))
    self.assert_process_exits(descendant_pid)

  def test_build_interrupt_kills_the_compiler_process_group(self) -> None:
    binary, source, build_script, pid_file = self.hanging_build()
    cancel_interrupt = threading.Event()

    def interrupt_when_started() -> None:
      deadline = time.monotonic() + 3
      while time.monotonic() < deadline and not cancel_interrupt.is_set():
        if pid_file.is_file():
          os.kill(os.getpid(), signal.SIGINT)
          return
        time.sleep(0.01)

    interrupter = threading.Thread(target=interrupt_when_started, daemon=True)
    interrupter.start()
    try:
      with self.assertRaises(KeyboardInterrupt):
        ensure_native_binary(
          binary,
          build_script,
          sources=(source,),
          repository_root=self.directory,
          timeout=10,
        )
    finally:
      cancel_interrupt.set()
      interrupter.join(timeout=1)

    descendant_pid = int(pid_file.read_text(encoding="utf-8"))
    self.assert_process_exits(descendant_pid)

  def test_managed_binary_rejects_a_mismatched_firmware_identity(self) -> None:
    managed = self.directory / ".simulator" / "sokkon-native"
    managed.parent.mkdir()
    managed.write_text(
      "#!/usr/bin/env python3\n"
      "import json, sys\n"
      "for _line in sys.stdin:\n"
      " print(json.dumps({'firmware': {'id': '99_stopwatch'}}), flush=True)\n",
      encoding="utf-8",
    )
    managed.chmod(0o700)
    with self.assertRaisesRegex(BackendProtocolError, "identity mismatch"):
      NativeSimulatorBackend(
        firmware_id="10_sokkon",
        repository_root=self.directory,
        auto_build=False,
      )

  def test_firmware_registry_is_exact_and_tracks_only_the_selected_main(self) -> None:
    self.assertEqual(firmware_spec("10_sokkon").binary_name, "sokkon-native")
    self.assertEqual(firmware_spec("99_stopwatch").binary_name, "stopwatch-native")
    for invalid in ("../99_stopwatch", "/tmp/main.cpp", "99_STOPWATCH", None):
      with self.subTest(invalid=invalid), self.assertRaises(BackendInputError):
        firmware_spec(invalid)

    sokkon_sources = native_sources(ROOT, firmware_id="10_sokkon")
    stopwatch_sources = native_sources(ROOT, firmware_id="99_stopwatch")
    self.assertIn(ROOT / "firmware/apps/10_sokkon/main.cpp", sokkon_sources)
    self.assertNotIn(ROOT / "firmware/apps/99_stopwatch/main.cpp", sokkon_sources)
    self.assertIn(ROOT / "firmware/apps/99_stopwatch/main.cpp", stopwatch_sources)
    self.assertNotIn(ROOT / "firmware/apps/10_sokkon/main.cpp", stopwatch_sources)

  def test_firmware_catalog_exposes_only_public_fixed_registry_metadata(self) -> None:
    self.assertEqual(
      firmware_catalog("99_stopwatch"),
      {
        "active": "99_stopwatch",
        "firmwares": [
          {"id": "10_sokkon", "label": "SOKKON"},
          {"id": "99_stopwatch", "label": "STOPWATCH"},
        ],
      },
    )
    catalog_text = repr(firmware_catalog("10_sokkon"))
    self.assertNotIn("main.cpp", catalog_text)
    self.assertNotIn("binary_name", catalog_text)

  def test_backend_manager_switches_transactionally_and_closes_old_process(self) -> None:
    created: list[NativeSimulatorBackend] = []

    def factory(firmware_id: str) -> NativeSimulatorBackend:
      backend = self.backend(firmware_id=firmware_id)
      created.append(backend)
      return backend

    with NativeSimulatorBackendManager(backend_factory=factory) as manager:
      initial = manager.snapshot()
      old_process = created[0]._process
      self.assertIsNotNone(old_process)
      switched = manager.switch_firmware("99_stopwatch")
      self.assertEqual(manager.firmware_id, "99_stopwatch")
      self.assertNotEqual(initial["pid"], switched["pid"])
      assert old_process is not None
      self.assertIsNotNone(old_process.poll())

      # Build & Run on the active firmware validates a fresh candidate too.
      switched_process = created[-1]._process
      same = manager.switch_firmware("99_stopwatch")
      self.assertEqual(len(created), 3)
      self.assertNotEqual(same["pid"], switched["pid"])
      assert switched_process is not None
      self.assertIsNotNone(switched_process.poll())

    active_process = created[-1]._process
    self.assertTrue(active_process is None or active_process.poll() is not None)

  def test_backend_manager_reset_transactionally_replaces_the_process(self) -> None:
    created: list[NativeSimulatorBackend] = []

    def factory(firmware_id: str) -> NativeSimulatorBackend:
      backend = self.backend(firmware_id=firmware_id)
      created.append(backend)
      return backend

    with NativeSimulatorBackendManager(backend_factory=factory) as manager:
      before = manager.perform_action("mode")
      old_process = created[0]._process
      reset = manager.reset()

      self.assertEqual(manager.firmware_id, "10_sokkon")
      self.assertEqual(len(created), 2)
      self.assertNotEqual(reset["pid"], before["pid"])
      assert old_process is not None
      self.assertIsNotNone(old_process.poll())

  def test_backend_manager_failed_reset_preserves_current_process(self) -> None:
    created: list[NativeSimulatorBackend] = []

    def factory(firmware_id: str) -> NativeSimulatorBackend:
      backend = self.backend(firmware_id=firmware_id)
      created.append(backend)
      return backend

    previous = os.environ.get("FAKE_NATIVE_MODE")
    try:
      os.environ["FAKE_NATIVE_MODE"] = "normal"
      with NativeSimulatorBackendManager(backend_factory=factory) as manager:
        current = manager.snapshot()
        os.environ["FAKE_NATIVE_MODE"] = "invalid"
        with self.assertRaises(BackendProtocolError):
          manager.reset()
        os.environ["FAKE_NATIVE_MODE"] = "normal"
        after = manager.snapshot()

        self.assertEqual(manager.firmware_id, "10_sokkon")
        self.assertEqual(after["pid"], current["pid"])
        self.assertEqual(len(created), 2)
        failed_process = created[1]._process
        self.assertTrue(failed_process is None or failed_process.poll() is not None)
    finally:
      if previous is None:
        os.environ.pop("FAKE_NATIVE_MODE", None)
      else:
        os.environ["FAKE_NATIVE_MODE"] = previous

  def test_backend_manager_keeps_current_process_when_candidate_fails(self) -> None:
    created: list[NativeSimulatorBackend] = []

    def factory(firmware_id: str) -> NativeSimulatorBackend:
      backend = self.backend(firmware_id=firmware_id)
      created.append(backend)
      return backend

    previous = os.environ.get("FAKE_NATIVE_MODE")
    try:
      os.environ["FAKE_NATIVE_MODE"] = "normal"
      with NativeSimulatorBackendManager(backend_factory=factory) as manager:
        current = manager.snapshot()
        os.environ["FAKE_NATIVE_MODE"] = "invalid"
        with self.assertRaises(BackendProtocolError):
          manager.switch_firmware("10_sokkon")
        os.environ["FAKE_NATIVE_MODE"] = "normal"
        after = manager.snapshot()
        self.assertEqual(manager.firmware_id, "10_sokkon")
        self.assertEqual(after["pid"], current["pid"])
        self.assertEqual(len(created), 2)
        failed_process = created[1]._process
        self.assertTrue(failed_process is None or failed_process.poll() is not None)
    finally:
      if previous is None:
        os.environ.pop("FAKE_NATIVE_MODE", None)
      else:
        os.environ["FAKE_NATIVE_MODE"] = previous

  def test_backend_manager_rejects_unregistered_ids_before_factory_call(self) -> None:
    requested: list[str] = []

    def factory(firmware_id: str) -> NativeSimulatorBackend:
      requested.append(firmware_id)
      return self.backend(firmware_id=firmware_id)

    with NativeSimulatorBackendManager(backend_factory=factory) as manager:
      for invalid in ("../99_stopwatch", " 99_stopwatch", "99_STOPWATCH", None):
        with self.subTest(invalid=invalid), self.assertRaises(BackendInputError):
          manager.switch_firmware(invalid)
      self.assertEqual(requested, ["10_sokkon"])


if __name__ == "__main__":
  unittest.main()
