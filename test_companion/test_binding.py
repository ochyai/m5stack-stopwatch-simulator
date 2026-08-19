from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from companion.binding import BindingError, load_binding, save_binding


DEVICE = "02AABBCCDDEE"
DEVICE_2 = "06AABBCCDDEE"


class BindingTest(unittest.TestCase):
  def test_binding_is_atomic_private_and_normalized(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "config" / "device.json"
      saved = save_binding(DEVICE.lower(), target)
      self.assertEqual(saved, target)
      self.assertEqual(load_binding(target), DEVICE)
      self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)

  def test_different_binding_requires_explicit_replace(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      target = Path(directory) / "device.json"
      save_binding(DEVICE, target)
      with self.assertRaises(BindingError):
        save_binding(DEVICE_2, target)
      save_binding(DEVICE_2, target, replace=True)
      self.assertEqual(load_binding(target), DEVICE_2)

  def test_binding_rejects_missing_malformed_and_symlink_files(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      root = Path(directory)
      with self.assertRaises(BindingError):
        load_binding(root / "missing.json")

      malformed = root / "malformed.json"
      malformed.write_text('{"device_id":"not-hex"}\n', encoding="utf-8")
      with self.assertRaises(BindingError):
        load_binding(malformed)

      symlink = root / "binding.json"
      symlink.symlink_to(malformed)
      with self.assertRaises(BindingError):
        load_binding(symlink)


if __name__ == "__main__":
  unittest.main()
