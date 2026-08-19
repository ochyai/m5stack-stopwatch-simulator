from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import textwrap
import time
import unittest

from simulator.backend import (
  BackendInputError,
  BackendProcessError,
  BackendProtocolError,
  BackendTimeoutError,
  NativeSimulatorBackend,
  binary_is_stale,
  normalize_configuration,
)


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


if __name__ == "__main__":
  unittest.main()
