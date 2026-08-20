#pragma once

// GENERATED FILE — do not edit by hand.
// Regenerate: python3 scripts/generate-font-metrics.py
//
// Measured from M5GFX 0.2.27 (MIT), the library the firmware links on the
// device. Only advance/offset measurements are reproduced here; no glyph
// bitmap is copied. These numbers are what LGFXBase::text_width and
// LGFXBase::draw_string consume, so the simulator lays text out exactly like
// the panel does.

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace sim_font {

struct Glyph {
  int16_t width;
  int16_t x_advance;
  int16_t x_offset;
};

struct Metrics {
  const char* name;
  int16_t height;     // font box height in device pixels
  int16_t baseline;   // baseline distance below the font box top
  int16_t y_advance;
  uint16_t first;     // code point of glyphs[0]
  uint16_t count;
  const Glyph* glyphs;

  // Out-of-range code points fall back to the first glyph, matching the
  // device's own substitution for an unmapped character.
  const Glyph& glyph(uint32_t code_point) const {
    const uint32_t index = code_point - first;
    return glyphs[index < count ? index : 0];
  }
};

inline constexpr Glyph kFont2Glyphs[] = {
    {   6,   6,   0}, {   3,   3,   0}, {   4,   4,   0}, {   9,   9,   0}, {   8,   8,   0}, {   9,   9,   0},
    {   9,   9,   0}, {   3,   3,   0}, {   7,   7,   0}, {   7,   7,   0}, {   8,   8,   0}, {   6,   6,   0},
    {   3,   3,   0}, {   6,   6,   0}, {   5,   5,   0}, {   7,   7,   0}, {   8,   8,   0}, {   8,   8,   0},
    {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0},
    {   8,   8,   0}, {   8,   8,   0}, {   3,   3,   0}, {   3,   3,   0}, {   6,   6,   0}, {   6,   6,   0},
    {   6,   6,   0}, {   8,   8,   0}, {   9,   9,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0},
    {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   4,   4,   0},
    {   8,   8,   0}, {   8,   8,   0}, {   7,   7,   0}, {  10,  10,   0}, {   8,   8,   0}, {   8,   8,   0},
    {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0},
    {   8,   8,   0}, {  10,  10,   0}, {   8,   8,   0}, {   8,   8,   0}, {   8,   8,   0}, {   4,   4,   0},
    {   7,   7,   0}, {   4,   4,   0}, {   7,   7,   0}, {   9,   9,   0}, {   5,   5,   0}, {   7,   7,   0},
    {   7,   7,   0}, {   7,   7,   0}, {   7,   7,   0}, {   7,   7,   0}, {   6,   6,   0}, {   7,   7,   0},
    {   7,   7,   0}, {   4,   4,   0}, {   5,   5,   0}, {   6,   6,   0}, {   4,   4,   0}, {   8,   8,   0},
    {   7,   7,   0}, {   8,   8,   0}, {   7,   7,   0}, {   8,   8,   0}, {   6,   6,   0}, {   6,   6,   0},
    {   5,   5,   0}, {   7,   7,   0}, {   8,   8,   0}, {   8,   8,   0}, {   6,   6,   0}, {   7,   7,   0},
    {   7,   7,   0}, {   5,   5,   0}, {   3,   3,   0}, {   5,   5,   0}, {   8,   8,   0}, {   6,   6,   0},
};

inline constexpr Glyph kFreeSansBold18pt7bGlyphs[] = {
    {   0,  10,   0}, {   5,  12,   4}, {  13,  17,   2}, {  20,  19,   0}, {  19,  19,   0}, {  29,  31,   1},
    {  22,  25,   2}, {   5,   9,   2}, {   9,  12,   1}, {   9,  12,   1}, {  12,  14,   0}, {  16,  20,   2},
    {   5,   9,   2}, {   9,  12,   1}, {   5,   9,   2}, {   9,  10,   0}, {  17,  19,   1}, {  10,  19,   3},
    {  17,  19,   1}, {  17,  19,   1}, {  16,  19,   2}, {  17,  19,   1}, {  18,  19,   1}, {  17,  19,   1},
    {  17,  19,   1}, {  17,  19,   1}, {   5,   9,   2}, {   5,   9,   2}, {  18,  20,   1}, {  17,  20,   2},
    {  18,  20,   1}, {  18,  21,   2}, {  32,  34,   1}, {  24,  24,   0}, {  20,  25,   3}, {  23,  25,   1},
    {  21,  25,   3}, {  19,  23,   3}, {  17,  22,   3}, {  24,  27,   1}, {  20,  26,   3}, {   5,  11,   3},
    {  16,  20,   1}, {  22,  25,   3}, {  17,  22,   3}, {  24,  30,   3}, {  20,  26,   3}, {  25,  27,   1},
    {  19,  24,   3}, {  25,  27,   1}, {  21,  25,   3}, {  20,  24,   2}, {  19,  23,   2}, {  20,  26,   3},
    {  22,  23,   1}, {  32,  34,   1}, {  22,  24,   1}, {  21,  22,   1}, {  19,  21,   1}, {   8,  12,   2},
    {  10,  10,   0}, {   8,  12,   1}, {  16,  20,   2}, {  21,  19,  -1}, {   7,   9,   1}, {  18,  20,   1},
    {  18,  22,   2}, {  17,  20,   1}, {  19,  22,   1}, {  18,  20,   1}, {  10,  12,   1}, {  18,  21,   1},
    {  17,  21,   2}, {   5,  10,   2}, {   7,  10,   0}, {  17,  20,   2}, {   5,   9,   2}, {  27,  31,   2},
    {  17,  21,   2}, {  19,  21,   1}, {  18,  22,   2}, {  19,  22,   1}, {  11,  14,   2}, {  17,  19,   1},
    {   9,  12,   1}, {  17,  21,   2}, {  19,  19,   0}, {  27,  27,   0}, {  18,  19,   1}, {  19,  19,   0},
    {  16,  18,   1}, {   9,  14,   1}, {   3,  10,   4}, {   9,  14,   3}, {  15,  18,   1},
};

inline constexpr Glyph kFreeSansBold24pt7bGlyphs[] = {
    {   0,  13,   0}, {   7,  16,   5}, {  18,  22,   2}, {  26,  26,   0}, {  25,  26,   1}, {  39,  42,   1},
    {  30,  34,   3}, {   7,  12,   3}, {  13,  16,   2}, {  13,  16,   1}, {  15,  18,   1}, {  23,  27,   2},
    {   7,  12,   2}, {  13,  16,   1}, {   7,  12,   2}, {  13,  13,   0}, {  24,  26,   1}, {  14,  26,   4},
    {  23,  26,   2}, {  23,  26,   2}, {  22,  26,   2}, {  23,  26,   2}, {  23,  26,   2}, {  23,  26,   1},
    {  24,  26,   1}, {  24,  26,   1}, {   7,  12,   2}, {   7,  12,   2}, {  23,  27,   2}, {  23,  27,   2},
    {  23,  27,   2}, {  24,  29,   3}, {  43,  46,   1}, {  32,  33,   0}, {  27,  33,   4}, {  30,  34,   2},
    {  28,  34,   4}, {  25,  31,   4}, {  24,  30,   4}, {  31,  36,   2}, {  27,  35,   4}, {   7,  15,   4},
    {  22,  27,   1}, {  30,  34,   4}, {  23,  29,   4}, {  33,  41,   4}, {  28,  35,   4}, {  33,  37,   2},
    {  26,  32,   4}, {  33,  37,   2}, {  28,  34,   4}, {  28,  32,   2}, {  27,  30,   2}, {  27,  35,   4},
    {  29,  31,   1}, {  43,  45,   1}, {  30,  32,   1}, {  29,  30,   1}, {  26,  29,   1}, {  11,  16,   3},
    {  14,  13,  -1}, {  11,  16,   1}, {  22,  27,   3}, {  28,  26,  -1}, {   9,  12,   1}, {  24,  27,   2},
    {  25,  29,   3}, {  23,  26,   2}, {  25,  29,   2}, {  24,  27,   2}, {  14,  16,   1}, {  24,  29,   2},
    {  23,  28,   3}, {   7,  13,   3}, {  10,  13,   0}, {  23,  27,   3}, {   7,  13,   3}, {  36,  42,   3},
    {  23,  29,   3}, {  25,  29,   2}, {  25,  29,   3}, {  25,  29,   2}, {  15,  18,   3}, {  24,  26,   1},
    {  12,  16,   2}, {  23,  29,   3}, {  25,  25,   0}, {  35,  37,   1}, {  24,  26,   1}, {  25,  26,   0},
    {  21,  24,   1}, {  13,  18,   2}, {   4,  13,   5}, {  13,  18,   3}, {  21,  23,   1},
};

inline constexpr Metrics kFonts[] = {
    {"Font2", 16, 13, 16, 32, 96, kFont2Glyphs},
    {"FreeSansBold18pt7b", 33, 25, 42, 32, 95, kFreeSansBold18pt7bGlyphs},
    {"FreeSansBold24pt7b", 47, 35, 56, 32, 95, kFreeSansBold24pt7bGlyphs},
};

inline constexpr size_t kFontCount = sizeof(kFonts) / sizeof(kFonts[0]);

// Falls back to the first font so an unnamed font still lays out somewhere
// deterministic instead of crashing a simulator run.
inline const Metrics& byName(const char* name) {
  if (name != nullptr) {
    for (size_t index = 0; index < kFontCount; ++index) {
      if (std::strcmp(kFonts[index].name, name) == 0) return kFonts[index];
    }
  }
  return kFonts[0];
}

}  // namespace sim_font
