from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from companion.actions import ActionHandler
from companion.capture import CaptureRecord, append_capture
from companion.config import CompanionConfig


JST = timezone(timedelta(hours=9))
FIXED_TIME = datetime(2026, 8, 19, 14, 5, 6, tzinfo=JST)


class CaptureTest(unittest.TestCase):
  def test_capture_is_created_only_when_appended(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "nested" / "Sokkon Inbox.md"
      self.assertFalse(target.exists())

      append_capture(
        target,
        CaptureRecord(
          timestamp=FIXED_TIME,
          mode="BUILD",
          context="Visual Studio Code",
          focus="RUNNING",
          elapsed_ms=65_432,
        ),
      )
      append_capture(
        target,
        CaptureRecord(
          timestamp=FIXED_TIME,
          mode="READ",
          context="Preview",
          focus="PAUSED",
          elapsed_ms=0,
        ),
      )

      content = target.read_text(encoding="utf-8")
      self.assertEqual(content.count("# Sokkon Inbox"), 1)
      self.assertIn("2026-08-19T14:05:06+09:00", content)
      self.assertIn("[BUILD] MARK — app: Visual Studio Code — focus: RUNNING 00:01:05.432", content)
      self.assertIn("[READ] MARK — app: Preview — focus: PAUSED 00:00:00.000", content)

  def test_action_handler_capture_and_optional_shortcut(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "Inbox.md"
      shortcuts: list[str] = []
      config = CompanionConfig(target, {"CAPTURE": "Archive Capture"})
      handler = ActionHandler(config, shortcut_runner=lambda name: not shortcuts.append(name))

      ok, reason = handler.handle(
        "CAPTURE",
        timestamp=FIXED_TIME,
        mode="BUILD",
        context="Xcode",
        focus="RUNNING",
        elapsed_ms=12_345,
      )
      self.assertTrue(ok)
      self.assertIsNone(reason)
      self.assertTrue(target.exists())
      self.assertEqual(shortcuts, ["Archive Capture"])

  def test_capture_remains_successful_when_optional_shortcut_fails(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "Inbox.md"
      handler = ActionHandler(
        CompanionConfig(target, {"CAPTURE": "Archive Capture"}),
        shortcut_runner=lambda _name: False,
      )
      with self.assertLogs("companion.actions", level="ERROR"):
        ok, reason = handler.handle(
          "CAPTURE",
          timestamp=FIXED_TIME,
          mode="BUILD",
          context="Xcode",
          focus="PAUSED",
          elapsed_ms=0,
        )
      self.assertTrue(ok)
      self.assertIsNone(reason)
      self.assertIn("[BUILD] MARK", target.read_text(encoding="utf-8"))

  def test_dry_run_has_no_file_or_shortcut_side_effect(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "Inbox.md"
      shortcuts: list[str] = []
      config = CompanionConfig(target, {"CAPTURE": "Archive Capture"})
      handler = ActionHandler(
        config,
        dry_run=True,
        shortcut_runner=lambda name: not shortcuts.append(name),
      )

      ok, reason = handler.handle(
        "CAPTURE",
        timestamp=FIXED_TIME,
        mode="BUILD",
        context="Xcode",
        focus="PAUSED",
        elapsed_ms=0,
      )
      self.assertFalse(ok)
      self.assertEqual(reason, "DRY_RUN_NOT_SAVED")
      self.assertFalse(target.exists())
      self.assertEqual(shortcuts, [])

  def test_dry_run_reports_skipped_configured_non_capture_action(self) -> None:
    handler = ActionHandler(
      CompanionConfig(Path("unused.md"), {"MODE_NEXT": "Next Mode"}),
      dry_run=True,
    )
    ok, reason = handler.handle(
      "MODE_NEXT",
      timestamp=FIXED_TIME,
      mode="READ",
      context="Xcode",
      focus="PAUSED",
      elapsed_ms=0,
    )
    self.assertFalse(ok)
    self.assertEqual(reason, "DRY_RUN_ACTION_SKIPPED")

  def test_capture_rejects_symlink_target(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      real_target = root / "real.md"
      real_target.write_text("untouched\n", encoding="utf-8")
      symlink = root / "Inbox.md"
      symlink.symlink_to(real_target)
      with self.assertRaises(OSError):
        append_capture(
          symlink,
          CaptureRecord(
            timestamp=FIXED_TIME,
            mode="BUILD",
            context="Xcode",
            focus="PAUSED",
            elapsed_ms=0,
          ),
        )
      self.assertEqual(real_target.read_text(encoding="utf-8"), "untouched\n")

  def test_fsync_failure_is_reported_as_capture_error(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "Inbox.md"
      handler = ActionHandler(CompanionConfig(target, {}))
      with self.assertLogs("companion.actions", level="ERROR"):
        with patch("companion.capture.os.fsync", side_effect=OSError("disk failure")):
          ok, reason = handler.handle(
            "CAPTURE",
            timestamp=FIXED_TIME,
            mode="BUILD",
            context="Xcode",
            focus="RUNNING",
            elapsed_ms=123,
          )
      self.assertFalse(ok)
      self.assertEqual(reason, "CAPTURE_WRITE_FAILED")


if __name__ == "__main__":
  unittest.main()
