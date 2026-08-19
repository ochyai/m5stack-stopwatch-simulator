from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from companion.cli import main


class CliTest(unittest.TestCase):
  def test_normal_start_requires_persistent_binding(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      missing = Path(directory) / "missing.json"
      with (
        self.assertLogs("companion.cli", level="ERROR"),
        patch("companion.cli.logging.basicConfig"),
        patch("companion.cli.detect_port") as detect,
      ):
        self.assertEqual(main(["--once", "--binding", str(missing)]), 2)
      detect.assert_not_called()

  def test_pair_only_handshakes_and_saves_identity(self) -> None:
    serial_context = MagicMock()
    serial_context.__enter__.return_value = MagicMock()
    session = MagicMock()
    session.handshake.return_value = ("02AABBCCDDEE", "0123456789ABCDEF")

    with (
      patch("companion.cli.detect_port", return_value="/dev/cu.synthetic"),
      patch("companion.cli.logging.basicConfig"),
      patch("companion.cli.SerialPort", return_value=serial_context),
      patch("companion.cli.CompanionSession", return_value=session),
      patch(
        "companion.cli.save_binding",
        return_value=Path("/tmp/synthetic-device.json"),
      ) as save,
      self.assertLogs("companion.cli", level="INFO"),
    ):
      self.assertEqual(main(["--pair"]), 0)

    session.handshake.assert_called_once_with()
    session.run.assert_not_called()
    save.assert_called_once_with(
      "02AABBCCDDEE",
      None,
      replace=False,
    )


if __name__ == "__main__":
  unittest.main()
