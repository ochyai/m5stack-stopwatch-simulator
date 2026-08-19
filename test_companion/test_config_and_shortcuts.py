from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from companion.actions import run_shortcut
from companion.config import ConfigError, load_config


class ConfigAndShortcutsTest(unittest.TestCase):
  def test_config_loads_relative_capture_and_event_shortcuts(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      path = root / "companion.json"
      path.write_text(
        json.dumps(
          {
            "capture_path": "captures/inbox.md",
            "shortcuts": {
              "event|capture": "Archive Capture",
              "MODE_NEXT": "Next Mode",
            },
          }
        ),
        encoding="utf-8",
      )

      config = load_config(path)
      self.assertEqual(config.capture_path, (root / "captures" / "inbox.md").resolve())
      self.assertEqual(config.shortcuts["CAPTURE"], "Archive Capture")
      self.assertEqual(config.shortcuts["MODE_NEXT"], "Next Mode")
      self.assertFalse(config.capture_path.exists())

  def test_config_rejects_unsafe_shortcut_name(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "companion.json"
      path.write_text(
        json.dumps({"shortcuts": {"CAPTURE": "--input-path"}}),
        encoding="utf-8",
      )
      with self.assertRaises(ConfigError):
        load_config(path)

  def test_shortcut_uses_argv_and_never_a_shell(self) -> None:
    class Process:
      def wait(self, *, timeout: float | None = None) -> int:
        return 0

    with patch("companion.actions.subprocess.Popen", return_value=Process()) as runner:
      self.assertTrue(run_shortcut("Archive Capture"))
    argv = runner.call_args.args[0]
    kwargs = runner.call_args.kwargs
    self.assertEqual(argv, ["/usr/bin/shortcuts", "run", "Archive Capture"])
    self.assertIs(kwargs["shell"], False)
    self.assertIs(kwargs["stdout"], subprocess.DEVNULL)


if __name__ == "__main__":
  unittest.main()
