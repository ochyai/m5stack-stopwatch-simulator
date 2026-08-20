"""Render a published frame to a PNG without a person at a browser.

The point of this module is that an agent can look at the panel.  It does not
draw anything itself: it loads `simulator/static/frame-renderer.js`, the same
module both simulator UIs import, into a headless browser and screenshots the
canvas.  A picture produced here is therefore the picture a person sees, not a
second opinion about what the firmware drew.

A headless Chrome/Chromium is optional.  When none is installed the caller gets
a clear message and the rest of a session still works, because every automated
check runs on the frame data rather than on pixels.
"""

from __future__ import annotations

from collections.abc import Sequence
import contextlib
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
RENDERER = REPOSITORY_ROOT / "simulator" / "static" / "frame-renderer.js"
DEVICE_SIZE = 466

# Ordered by how likely a Mac or a Linux CI box is to have it.
BROWSER_CANDIDATES = (
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
  "google-chrome",
  "google-chrome-stable",
  "chromium",
  "chromium-browser",
  "microsoft-edge",
)


class ScreenshotError(RuntimeError):
  """No usable browser, or it did not produce an image."""


def find_browser(explicit: str | None = None) -> str:
  """Locate a headless-capable browser binary."""
  candidates = [explicit] if explicit else []
  candidates.append(os.environ.get("SIMULATOR_BROWSER"))
  candidates.extend(BROWSER_CANDIDATES)
  for candidate in candidates:
    if not candidate:
      continue
    path = Path(candidate)
    if path.is_absolute():
      if path.is_file() and os.access(path, os.X_OK):
        return str(path)
      continue
    resolved = shutil.which(candidate)
    if resolved:
      return resolved
  raise ScreenshotError(
    "no headless Chrome/Chromium found; install one or set SIMULATOR_BROWSER"
  )


LABEL_HEIGHT = 34
SHEET_COLUMNS = 3


@dataclass(frozen=True)
class Panel:
  """One labelled frame to draw on a page."""

  label: str
  frame: dict[str, Any]
  screen: dict[str, Any] = field(default_factory=dict)


def sheet_size(count: int, *, labelled: bool) -> tuple[int, int, int]:
  """Return the window size and column count for ``count`` panels."""
  columns = 1 if count <= 1 else min(SHEET_COLUMNS, count)
  rows = max(1, -(-count // columns))
  cell_height = DEVICE_SIZE + (LABEL_HEIGHT if labelled else 0)
  return columns * DEVICE_SIZE, rows * cell_height, columns


def build_page(panels: Sequence[Panel], *, labelled: bool = False) -> str:
  """Build a self-contained page that replays every panel.

  The renderer is inlined rather than fetched: a ``file://`` page cannot import
  a module across origins, and inlining keeps the single source file as the
  single source of truth.
  """
  renderer = RENDERER.read_text(encoding="utf-8")
  payload = json.dumps(
    [{"label": panel.label, "frame": panel.frame, "screen": panel.screen} for panel in panels],
    ensure_ascii=False,
    allow_nan=False,
  )
  # The payload is embedded in a module script, so the only sequence that could
  # end the element early is a literal closing tag inside a string.
  payload = payload.replace("</", "<\\/")
  _width, _height, columns = sheet_size(len(panels), labelled=labelled)
  label_display = "block" if labelled else "none"
  return f"""<!doctype html>
<meta charset="utf-8">
<title>device frames</title>
<style>
  html, body {{ margin: 0; background: #000; }}
  main {{
    display: grid;
    grid-template-columns: repeat({columns}, {DEVICE_SIZE}px);
    width: max-content;
  }}
  figure {{ margin: 0; }}
  canvas {{ display: block; width: {DEVICE_SIZE}px; height: {DEVICE_SIZE}px; }}
  figcaption {{
    display: {label_display};
    height: {LABEL_HEIGHT}px;
    box-sizing: border-box;
    padding: 8px 12px;
    color: #d6d3d6;
    background: #0b0d0e;
    font: 600 15px -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    overflow: hidden;
    white-space: nowrap;
  }}
</style>
<main id="sheet"></main>
<script type="module">
{renderer}

const panels = {payload};
const sheet = document.getElementById("sheet");
for (const panel of panels) {{
  const figure = document.createElement("figure");
  const canvas = document.createElement("canvas");
  canvas.width = {DEVICE_SIZE};
  canvas.height = {DEVICE_SIZE};
  const context = canvas.getContext("2d", {{ alpha: false }});
  renderFrame(context, panel.frame);
  canvas.style.opacity = String(screenOpacity(panel.screen, panel.frame));
  const caption = document.createElement("figcaption");
  caption.textContent = panel.label;
  figure.append(canvas, caption);
  sheet.append(figure);
}}
document.title = "ready";
</script>
"""


@contextlib.contextmanager
def _workspace_directory(existing: str | Path | None):
  """Yield a scratch directory, creating a throwaway one when needed."""
  if existing is not None:
    path = Path(existing)
    path.mkdir(parents=True, exist_ok=True)
    yield path
    return
  with tempfile.TemporaryDirectory(prefix="m5-simulator-shot-") as created:
    yield Path(created)


def capture_frame(
  frame: dict[str, Any],
  destination: str | Path,
  *,
  screen: dict[str, Any] | None = None,
  browser: str | None = None,
  timeout: float = 60.0,
  workspace: str | Path | None = None,
) -> Path:
  """Render one frame to a PNG and return its path."""
  return capture_panels(
    [Panel(label="frame", frame=frame, screen=screen or {})],
    destination,
    labelled=False,
    browser=browser,
    timeout=timeout,
    workspace=workspace,
  )


def capture_panels(
  panels: Sequence[Panel],
  destination: str | Path,
  *,
  labelled: bool = True,
  browser: str | None = None,
  timeout: float = 60.0,
  workspace: str | Path | None = None,
) -> Path:
  """Render every panel onto one PNG contact sheet.

  A browser start costs far more than the drawing does, so a whole session is
  one launch and one image an agent can read in a single look.
  """
  if not panels:
    raise ScreenshotError("no frames to capture")
  executable = find_browser(browser)
  output = Path(destination).resolve()
  output.parent.mkdir(parents=True, exist_ok=True)
  if output.exists():
    output.unlink()
  width, height, _columns = sheet_size(len(panels), labelled=labelled)

  with _workspace_directory(workspace) as workspace_path:
    workspace = workspace_path
    page = Path(workspace) / f"{output.stem}.html"
    page.write_text(build_page(panels, labelled=labelled), encoding="utf-8")
    command = [
      executable,
      "--headless=new",
      "--disable-gpu",
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-extensions",
      "--disable-background-networking",
      "--hide-scrollbars",
      f"--user-data-dir={workspace}/profile",
      f"--screenshot={output}",
      f"--window-size={width},{height}",
      "--virtual-time-budget=3000",
      page.as_uri(),
    ]
    process = subprocess.Popen(
      command,
      stdin=subprocess.DEVNULL,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.PIPE,
      start_new_session=True,
    )
    try:
      # Some Chrome builds write the screenshot and then keep the process
      # alive. Wait for a stable file instead of for an exit that may not come.
      deadline = time.monotonic() + timeout
      stable_size = -1
      while time.monotonic() < deadline:
        if process.poll() is not None and output.is_file():
          break
        if output.is_file():
          size = output.stat().st_size
          if size > 0 and size == stable_size:
            break
          stable_size = size
        time.sleep(0.1)
      else:
        raise ScreenshotError(f"{Path(executable).name} did not produce {output.name} in time")
    finally:
      if process.poll() is None:
        process.terminate()
        try:
          process.wait(timeout=5)
        except subprocess.TimeoutExpired:
          process.kill()
          process.wait(timeout=5)
      if process.stderr is not None:
        process.stderr.close()

  if not output.is_file() or output.stat().st_size == 0:
    raise ScreenshotError(f"{Path(executable).name} produced no image at {output}")
  return output


__all__ = [
  "Panel",
  "ScreenshotError",
  "build_page",
  "capture_frame",
  "capture_panels",
  "find_browser",
  "sheet_size",
]
