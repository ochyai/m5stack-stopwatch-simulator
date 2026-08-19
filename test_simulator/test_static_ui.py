"""Static acceptance checks for the simulator's device presentation.

The checks intentionally use only the Python standard library so the same UI
asset contract runs on a fresh Mac and in the Ubuntu CI job.
"""

from __future__ import annotations

from pathlib import Path
import re
import struct
import unittest
import zlib


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "simulator" / "static"


def _css_rules(css: str, selector: str) -> str:
  pattern = re.compile(
    rf"(?m)^{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}"
  )
  return "\n".join(match.group("body") for match in pattern.finditer(css))


def _pixel_value(declarations: str, property_name: str) -> int:
  match = re.search(
    rf"(?:^|;)\s*{re.escape(property_name)}\s*:\s*(-?\d+)px\s*(?:;|$)",
    declarations,
  )
  if match is None:
    raise AssertionError(f"missing {property_name}: <number>px declaration")
  return int(match.group(1))


class StaticSimulatorUITest(unittest.TestCase):
  def test_device_shell_is_a_valid_high_resolution_png(self) -> None:
    path = STATIC / "device-shell.png"
    self.assertTrue(path.is_file(), "real device shell asset is missing")
    data = path.read_bytes()
    self.assertGreater(len(data), 50_000, "shell image looks like a placeholder")
    self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")

    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(data):
      self.assertGreaterEqual(len(data) - offset, 12, "truncated PNG chunk")
      length = struct.unpack_from(">I", data, offset)[0]
      chunk_type = data[offset + 4:offset + 8]
      payload_start = offset + 8
      payload_end = payload_start + length
      crc_end = payload_end + 4
      self.assertLessEqual(crc_end, len(data), "PNG chunk exceeds file size")
      payload = data[payload_start:payload_end]
      expected_crc = struct.unpack_from(">I", data, payload_end)[0]
      actual_crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
      self.assertEqual(actual_crc, expected_crc, f"bad {chunk_type!r} CRC")
      chunks.append((chunk_type, payload))
      offset = crc_end
      if chunk_type == b"IEND":
        break

    self.assertEqual(offset, len(data), "unexpected data after PNG IEND")
    self.assertTrue(chunks)
    self.assertEqual(chunks[0][0], b"IHDR")
    self.assertEqual(len(chunks[0][1]), 13)
    width, height, bit_depth, _color_type, compression, filtering, interlace = (
      struct.unpack(">IIBBBBB", chunks[0][1])
    )
    self.assertGreaterEqual(width, 2 * 466)
    self.assertGreaterEqual(height, 2 * 466)
    self.assertEqual(width, height, "round device shell source should be square")
    self.assertIn(bit_depth, (8, 16))
    self.assertEqual(compression, 0)
    self.assertEqual(filtering, 0)
    self.assertIn(interlace, (0, 1))
    self.assertEqual(chunks[-1], (b"IEND", b""))

    compressed_pixels = b"".join(
      payload for chunk_type, payload in chunks if chunk_type == b"IDAT"
    )
    self.assertTrue(compressed_pixels, "PNG has no IDAT pixels")
    decoded_pixels = zlib.decompress(compressed_pixels)
    self.assertGreaterEqual(len(decoded_pixels), width * height)

  def test_javascript_renders_native_frame_commands_and_font_size(self) -> None:
    javascript = (STATIC / "app.js").read_text(encoding="utf-8")
    self.assertIn("frame?.commands", javascript)
    self.assertIn("for (const command of commands)", javascript)
    self.assertIn("renderFrame(snapshot.frame || {}, screen)", javascript)
    for operation in (
      "fillscreen",
      "drawcircle",
      "fillcircle",
      "drawarc",
      "fillroundrect",
      "drawstring",
    ):
      self.assertIn(f'"{operation}"', javascript)

    font_start = javascript.index("function fontForCommand")
    font_end = javascript.index("function applyTextDatum", font_start)
    font_function = javascript[font_start:font_end]
    self.assertIn('["font_size", "size_px", "text_size"]', font_function)
    self.assertIn("fontSize", font_function)
    self.assertIn("px -apple-system", font_function)
    self.assertIn("context.font = fontForCommand(command, renderState)", javascript)
    self.assertIn("context.fillText(text, x, y)", javascript)

  def test_css_uses_shell_image_and_places_upper_side_buttons(self) -> None:
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    shell = _css_rules(css, ".device-shell")
    common_button = _css_rules(css, ".hardware-button")
    button_a = _css_rules(css, ".hardware-button-a")
    button_b = _css_rules(css, ".hardware-button-b")
    for selector, declarations in (
      (".device-shell", shell),
      (".hardware-button", common_button),
      (".hardware-button-a", button_a),
      (".hardware-button-b", button_b),
    ):
      self.assertTrue(declarations, f"missing CSS rule for {selector}")

    self.assertRegex(
      shell,
      r'background\s*:[^;]*url\(["\']?/static/device-shell\.png["\']?\)',
    )
    self.assertIn("position: absolute", shell)
    self.assertIn("position: absolute", common_button)

    shell_width = _pixel_value(shell, "width")
    shell_height = _pixel_value(shell, "height")
    button_top = _pixel_value(common_button, "top")
    button_a_left = _pixel_value(button_a, "left")
    button_b_right = _pixel_value(button_b, "right")
    self.assertGreaterEqual(button_top, 0)
    self.assertLess(button_top, shell_height // 3, "A/B must stay in upper third")
    self.assertGreaterEqual(button_a_left, 0)
    self.assertLess(button_a_left, shell_width // 4, "A must stay at upper-left")
    self.assertGreaterEqual(button_b_right, 0)
    self.assertLess(button_b_right, shell_width // 4, "B must stay at upper-right")


if __name__ == "__main__":
  unittest.main()
