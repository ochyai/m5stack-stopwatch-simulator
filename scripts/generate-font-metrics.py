#!/usr/bin/env python3
"""Derive device font metrics from the installed M5GFX package.

The simulator has to answer one question exactly like the panel does: how wide
is this string, and where does each glyph land?  `LGFXBase::text_width` and
`LGFXBase::draw_string` answer it from per-glyph advance/offset numbers, so this
script measures those numbers from the fonts the firmware actually selects and
writes them into a generated C++ header.

Only measurements are extracted.  No glyph bitmap is copied into this
repository, and the generated header records where the numbers came from.

Usage:
  python3 scripts/generate-font-metrics.py            # write the header
  python3 scripts/generate-font-metrics.py --check    # fail if it is stale
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPOSITORY_ROOT / "simulator" / "native" / "include" / "font_metrics.hpp"

# The fonts firmware/apps and firmware/shared actually pass to setFont().
BITMAP_FONTS = {"Font2": "Font16.h"}
GFX_FONTS = {
  "FreeSansBold18pt7b": "GFXFF/FreeSansBold18pt7b.h",
  "FreeSansBold24pt7b": "GFXFF/FreeSansBold24pt7b.h",
}


class GeneratorError(RuntimeError):
  """The package is missing or does not have the expected shape."""


@dataclass(frozen=True)
class Glyph:
  width: int
  x_advance: int
  x_offset: int


@dataclass(frozen=True)
class FontMetrics:
  name: str
  height: int
  baseline: int
  y_advance: int
  first: int
  glyphs: tuple[Glyph, ...]


def find_package(repository_root: Path = REPOSITORY_ROOT) -> tuple[Path, str]:
  """Return the M5GFX font directory and a human-readable package version."""
  candidates = sorted(repository_root.glob("**/libdeps/*/M5GFX"))
  for package in candidates:
    fonts = package / "src" / "lgfx" / "Fonts"
    if not fonts.is_dir():
      continue
    version = "unknown version"
    manifest = package / "library.json"
    if manifest.is_file():
      try:
        version = str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
      except (KeyError, ValueError):
        pass
    return fonts, version
  raise GeneratorError(
    "M5GFX is not installed. Run `pio pkg install --environment 10_sokkon` first."
  )


def _defined_integer(source: str, name: str) -> int:
  match = re.search(rf"^#define\s+{re.escape(name)}\s+(\d+)\s*$", source, re.MULTILINE)
  if match is None:
    raise GeneratorError(f"missing #define {name}")
  return int(match.group(1))


def _resolve_conditionals(body: str, source: str) -> str:
  """Keep the branch the device build keeps.

  Font16.h selects between a grave accent and a degree symbol with an #ifdef.
  Measuring both branches would double-count eight glyphs, so resolve the
  conditional the same way the compiler does for this package.
  """
  defined = set(re.findall(r"^#define\s+(\w+)", source, re.MULTILINE))

  def resolve(match: re.Match[str]) -> str:
    directive, symbol, taken, other = match.group(1), match.group(2), match.group(3), match.group(4)
    is_defined = symbol in defined
    keep = is_defined if directive == "ifdef" else not is_defined
    return taken if keep else (other or "")

  pattern = re.compile(
    r"#(ifdef|ifndef)\s+(\w+)\n(.*?)(?:#else\n(.*?))?#endif\n",
    re.DOTALL,
  )
  resolved, replaced = pattern.subn(resolve, body)
  if "#" in resolved and replaced == 0 and "#" in body:
    raise GeneratorError("unresolved preprocessor directive in width table")
  return resolved


def parse_bitmap_font(name: str, path: Path) -> FontMetrics:
  """Read a classic width-table font such as Font2 (Font16.h)."""
  source = path.read_text(encoding="utf-8", errors="replace")
  suffix = re.search(r"widtbl_(\w+)\s*\[", source)
  if suffix is None:
    raise GeneratorError(f"{path.name} has no width table")
  key = suffix.group(1)
  height = _defined_integer(source, f"chr_hgt_{key}")
  baseline = _defined_integer(source, f"baseline_{key}")
  first = _defined_integer(source, f"firstchr_{key}")
  count = _defined_integer(source, f"nr_chrs_{key}")

  table_start = source.index(f"widtbl_{key}")
  body_start = source.index("{", table_start) + 1
  body_end = source.index("}", body_start)
  body = _resolve_conditionals(source[body_start:body_end], source)
  body = re.sub(r"//[^\n]*", "", body)
  widths = [int(value) for value in re.findall(r"-?\d+", body)]
  if len(widths) != count:
    raise GeneratorError(
      f"{path.name}: expected {count} widths, measured {len(widths)}"
    )

  # A classic bitmap font advances by its tabulated width and has no bearing.
  glyphs = tuple(Glyph(width=width, x_advance=width, x_offset=0) for width in widths)
  return FontMetrics(
    name=name,
    height=height,
    baseline=baseline,
    y_advance=height,
    first=first,
    glyphs=glyphs,
  )


GLYPH_ROW = re.compile(
  r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\}"
)


def parse_gfx_font(name: str, path: Path) -> FontMetrics:
  """Read an Adafruit-GFX style font table (FreeSansBold*7b.h)."""
  source = path.read_text(encoding="utf-8", errors="replace")
  table_start = source.find(f"{name}Glyphs[]")
  if table_start < 0:
    raise GeneratorError(f"{path.name} has no {name}Glyphs table")
  body_start = source.index("{", table_start) + 1
  body_end = source.index("};", body_start)
  rows = GLYPH_ROW.findall(source[body_start:body_end])
  if not rows:
    raise GeneratorError(f"{path.name}: no glyph rows found")

  trailer = re.search(
    rf"{re.escape(name)}\s+PROGMEM\s*=\s*\{{(.*?)\}}\s*;", source, re.DOTALL
  )
  if trailer is None:
    raise GeneratorError(f"{path.name}: no {name} font descriptor")
  numbers = re.findall(r"0x[0-9a-fA-F]+|\d+", trailer.group(1))
  if len(numbers) < 3:
    raise GeneratorError(f"{path.name}: unexpected font descriptor")
  first = int(numbers[-3], 0)
  last = int(numbers[-2], 0)
  y_advance = int(numbers[-1], 0)

  # ``GFXfont::getDefaultMetric`` walks ``last - first`` entries, so the table
  # is measured exactly the way the device measures it.
  measured = rows[: last - first]
  above = 0
  below = 0
  for _offset, width, height, _advance, _x_offset, y_offset in measured:
    ascent = -int(y_offset)
    above = max(above, ascent)
    below = max(below, int(height) - ascent)

  glyphs = tuple(
    Glyph(width=int(width), x_advance=int(advance), x_offset=int(x_offset))
    for _offset, width, _height, advance, x_offset, _y_offset in rows
  )
  return FontMetrics(
    name=name,
    height=above + below,
    baseline=above,
    y_advance=y_advance,
    first=first,
    glyphs=glyphs,
  )


def collect(fonts_directory: Path) -> list[FontMetrics]:
  metrics: list[FontMetrics] = []
  for name, relative in BITMAP_FONTS.items():
    metrics.append(parse_bitmap_font(name, fonts_directory / relative))
  for name, relative in GFX_FONTS.items():
    metrics.append(parse_gfx_font(name, fonts_directory / relative))
  return metrics


def _identifier(name: str) -> str:
  return "k" + re.sub(r"[^0-9A-Za-z]", "", name) + "Glyphs"


def render_header(metrics: list[FontMetrics], version: str) -> str:
  lines = [
    "#pragma once",
    "",
    "// GENERATED FILE — do not edit by hand.",
    "// Regenerate: python3 scripts/generate-font-metrics.py",
    "//",
    f"// Measured from M5GFX {version} (MIT), the library the firmware links on the",
    "// device. Only advance/offset measurements are reproduced here; no glyph",
    "// bitmap is copied. These numbers are what LGFXBase::text_width and",
    "// LGFXBase::draw_string consume, so the simulator lays text out exactly like",
    "// the panel does.",
    "",
    "#include <cstddef>",
    "#include <cstdint>",
    "#include <cstring>",
    "",
    "namespace sim_font {",
    "",
    "struct Glyph {",
    "  int16_t width;",
    "  int16_t x_advance;",
    "  int16_t x_offset;",
    "};",
    "",
    "struct Metrics {",
    "  const char* name;",
    "  int16_t height;     // font box height in device pixels",
    "  int16_t baseline;   // baseline distance below the font box top",
    "  int16_t y_advance;",
    "  uint16_t first;     // code point of glyphs[0]",
    "  uint16_t count;",
    "  const Glyph* glyphs;",
    "",
    "  // Out-of-range code points fall back to the first glyph, matching the",
    "  // device's own substitution for an unmapped character.",
    "  const Glyph& glyph(uint32_t code_point) const {",
    "    const uint32_t index = code_point - first;",
    "    return glyphs[index < count ? index : 0];",
    "  }",
    "};",
    "",
  ]

  for font in metrics:
    identifier = _identifier(font.name)
    lines.append(f"inline constexpr Glyph {identifier}[] = {{")
    for index in range(0, len(font.glyphs), 6):
      chunk = font.glyphs[index : index + 6]
      row = " ".join(
        f"{{{glyph.width:4d},{glyph.x_advance:4d},{glyph.x_offset:4d}}},"
        for glyph in chunk
      )
      lines.append(f"    {row}")
    lines.append("};")
    lines.append("")

  lines.append("inline constexpr Metrics kFonts[] = {")
  for font in metrics:
    lines.append(
      f'    {{"{font.name}", {font.height}, {font.baseline}, {font.y_advance}, '
      f"{font.first}, {len(font.glyphs)}, {_identifier(font.name)}}},"
    )
  lines.append("};")
  lines.extend(
    [
      "",
      "inline constexpr size_t kFontCount = sizeof(kFonts) / sizeof(kFonts[0]);",
      "",
      "// Falls back to the first font so an unnamed font still lays out somewhere",
      "// deterministic instead of crashing a simulator run.",
      "inline const Metrics& byName(const char* name) {",
      "  if (name != nullptr) {",
      "    for (size_t index = 0; index < kFontCount; ++index) {",
      "      if (std::strcmp(kFonts[index].name, name) == 0) return kFonts[index];",
      "    }",
      "  }",
      "  return kFonts[0];",
      "}",
      "",
      "}  // namespace sim_font",
      "",
    ]
  )
  return "\n".join(lines)


def main(argv: list[str]) -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--check",
    action="store_true",
    help="verify the committed header still matches the installed package",
  )
  arguments = parser.parse_args(argv)

  try:
    fonts_directory, version = find_package()
    metrics = collect(fonts_directory)
  except GeneratorError as error:
    print(f"font metrics: {error}", file=sys.stderr)
    return 2

  header = render_header(metrics, version)
  if arguments.check:
    current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
    if current != header:
      print(
        f"font metrics: {OUTPUT.relative_to(REPOSITORY_ROOT)} is stale; "
        "re-run scripts/generate-font-metrics.py",
        file=sys.stderr,
      )
      return 1
    print(f"font metrics: up to date against M5GFX {version}")
    return 0

  OUTPUT.write_text(header, encoding="utf-8")
  summary = ", ".join(
    f"{font.name}(h{font.height}/b{font.baseline}/{len(font.glyphs)} glyphs)"
    for font in metrics
  )
  print(f"font metrics: wrote {OUTPUT.relative_to(REPOSITORY_ROOT)} from M5GFX {version}")
  print(f"font metrics: {summary}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
