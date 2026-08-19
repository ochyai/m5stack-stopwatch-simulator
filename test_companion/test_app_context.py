from __future__ import annotations

import subprocess
import unittest

from companion.app_context import FALLBACK_APP, classify_app, frontmost_app_name


class AppContextTest(unittest.TestCase):
  def test_classification(self) -> None:
    cases = {
      "Visual Studio Code": "BUILD",
      "Xcode Beta": "BUILD",
      "zoom.us": "MEET",
      "Microsoft Teams": "MEET",
      "Keynote": "PRESENT",
      "Microsoft PowerPoint": "PRESENT",
      "Preview": "READ",
      "Safari": "READ",
      "TouchDesigner": "BUILD",
      "Processing": "BUILD",
      "Unity Hub": "BUILD",
      "Arduino IDE": "BUILD",
      "Ableton Live 12 Suite": "BUILD",
      "OBS Studio": "PRESENT",
      "Codex": "BUILD",
      "Ollama": "BUILD",
      "Slack": "MEET",
      "ChatGPT": "BUILD",
      "Finder": "NOW",
      "": "NOW",
    }
    for app_name, expected in cases.items():
      with self.subTest(app_name=app_name):
        self.assertEqual(classify_app(app_name), expected)

  def test_osascript_lookup_uses_argv_without_shell(self) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
      calls.append((argv, kwargs))
      return subprocess.CompletedProcess(argv, 0, stdout="Visual Studio Code\n", stderr="")

    self.assertEqual(frontmost_app_name(runner=runner), "Visual Studio Code")
    argv, kwargs = calls[0]
    self.assertEqual(argv[0:3], ["/usr/bin/osascript", "-l", "JavaScript"])
    self.assertIn("NSWorkspace", argv[-1])
    self.assertNotIn("System Events", argv[-1])
    self.assertIs(kwargs["shell"], False)

  def test_osascript_failure_has_safe_fallback(self) -> None:
    def missing_runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
      raise FileNotFoundError(argv[0])

    def failed_runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
      return subprocess.CompletedProcess(argv, 1, stdout="", stderr="denied")

    self.assertEqual(frontmost_app_name(runner=missing_runner), FALLBACK_APP)
    self.assertEqual(frontmost_app_name(runner=failed_runner), FALLBACK_APP)


if __name__ == "__main__":
  unittest.main()
