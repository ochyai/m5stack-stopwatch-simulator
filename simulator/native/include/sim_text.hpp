#pragma once

// Device-accurate text layout.
//
// This is a port of `LGFXBase::text_width` and the geometry half of
// `LGFXBase::draw_string` from the M5GFX version the firmware links, driven by
// the measurements in the generated `font_metrics.hpp`.  The integer fixed
// point and the truncating shifts are kept as they are on the device, because
// firmware code such as `10_sokkon`'s ellipsis logic branches on the exact
// `textWidth` value.  An approximation here would make the simulator agree with
// itself and disagree with the panel.

#include "font_metrics.hpp"

#include <cstdint>
#include <string>
#include <vector>

namespace sim_text {

// LovyanGFX text datum bits.  Only the combinations this HAL exposes are named.
enum Datum : int {
  kTopLeft = 0,
  kTopCenter = 1,
  kTopRight = 2,
  kMiddleLeft = 4,
  kMiddleCenter = 5,
  kMiddleRight = 6,
  kBottomLeft = 8,
  kBottomCenter = 9,
  kBottomRight = 10,
  kBaselineLeft = 16,
  kBaselineCenter = 17,
  kBaselineRight = 18,
};

inline int32_t fixedScale(float size) {
  return static_cast<int32_t>(65536.0F * size);
}

inline int32_t applyScale(int32_t value, int32_t fixed_scale) {
  return static_cast<int32_t>(
      (static_cast<int64_t>(value) * fixed_scale) >> 16);
}

// The device walks bytes and skips control characters.
inline bool isPrintable(unsigned char character) { return character >= 0x20; }

inline int32_t textWidth(const sim_font::Metrics& metrics, const char* text,
                         float size_x = 1.0F) {
  if (text == nullptr || text[0] == '\0') return 0;
  const int32_t sx = fixedScale(size_x);
  int32_t left = 0;
  int32_t right = 0;
  for (const char* cursor = text; *cursor != '\0'; ++cursor) {
    const unsigned char character = static_cast<unsigned char>(*cursor);
    if (!isPrintable(character)) continue;
    const sim_font::Glyph& glyph = metrics.glyph(character);
    const int32_t x_offset = applyScale(glyph.x_offset, sx);
    if (left == 0 && right == 0 && glyph.x_offset < 0) {
      left = right = -x_offset;
    }
    const int32_t advance = applyScale(glyph.x_advance, sx);
    const int32_t ink = applyScale(glyph.width, sx) + x_offset;
    right = left + (advance > ink ? advance : ink);
    left += advance;
  }
  return right;
}

// Everything a renderer needs to place the string exactly where the panel
// places it, in device pixels.
struct Layout {
  int32_t left = 0;      // pen origin of the first glyph
  int32_t top = 0;       // font box top
  int32_t baseline = 0;  // baseline row
  int32_t width = 0;     // textWidth of the whole string
  int32_t height = 0;    // font box height
  std::vector<int32_t> pen;  // pen origin per printable character
};

inline Layout layout(const sim_font::Metrics& metrics, const char* text,
                     int32_t x, int32_t y, int datum, float size_x = 1.0F,
                     float size_y = 1.0F) {
  const int32_t sx = fixedScale(size_x);
  const int32_t sy = fixedScale(size_y);

  Layout result;
  result.width = textWidth(metrics, text, size_x);
  result.height = applyScale(metrics.height, sy);

  // Vertical datum: the font box, not the ink, is what the device anchors.
  if (datum & kMiddleLeft) {
    y -= result.height >> 1;
  } else if (datum & kBottomLeft) {
    y -= result.height;
  } else if (datum & kBaselineLeft) {
    y -= applyScale(metrics.baseline, sy);
  }

  if (datum & kTopCenter) {
    x -= result.width >> 1;
  } else if (datum & kTopRight) {
    x -= result.width;
  }

  result.top = y;
  result.baseline = y + applyScale(metrics.baseline, sy);

  int32_t pen = x;
  if (text != nullptr) {
    for (const char* cursor = text; *cursor != '\0'; ++cursor) {
      const unsigned char character = static_cast<unsigned char>(*cursor);
      if (!isPrintable(character)) continue;
      const sim_font::Glyph& first = metrics.glyph(character);
      // A negative left bearing on the first glyph shifts the whole run right
      // so the ink still starts at the anchor.
      if (first.x_offset < 0) pen -= applyScale(first.x_offset, sx);
      break;
    }
    for (const char* cursor = text; *cursor != '\0'; ++cursor) {
      const unsigned char character = static_cast<unsigned char>(*cursor);
      if (!isPrintable(character)) continue;
      result.pen.push_back(pen);
      pen += applyScale(metrics.glyph(character).x_advance, sx);
    }
  }
  result.left = result.pen.empty() ? x : result.pen.front();
  return result;
}

}  // namespace sim_text
