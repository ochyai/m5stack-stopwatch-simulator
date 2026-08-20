"""Scripted simulator sessions.

A session is a small text script of the same commands the UI sends: press a
button, let virtual time pass, change the host scenario, take a shot.  Because
the native runner is driven entirely by those commands and by virtual time, a
script replays byte-for-byte identically on any machine.

That gives three things one mechanism:

* **replay** — reproduce a bug or a demo without touching a browser,
* **golden frames** — lock what the production firmware draws, so an unintended
  layout change fails a test instead of shipping,
* **inspection** — report what is off-screen, outside the round panel, or
  overlapping, which is the part a person or an agent has to judge otherwise.

The panel is a 466 x 466 *round* AMOLED, so the visible area is the inscribed
circle. Content in the corners is drawn and never seen; that is a finding, not
an opinion.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import sys
from typing import Any

from .backend import (
  ACTION_COMMANDS,
  CONFIGURATION_KEYS,
  DEFAULT_FIRMWARE_ID,
  MODE_ORDER,
  BackendInputError,
)


DEVICE_SIZE = 466
DEVICE_RADIUS = DEVICE_SIZE / 2
DEVICE_CENTER = DEVICE_SIZE / 2
MAX_ADVANCE_MS = 24 * 60 * 60 * 1000
MAX_STEPS = 2_000

STEP_KINDS = ("action", "touch", "advance", "configure", "reset", "shot", "note")
BOOLEAN_KEYS = ("connected", "charging")
INTEGER_KEYS = ("latency_ms", "battery_percent")
FLOAT_KEYS = ("time_scale", "tilt_x", "tilt_y")


class SessionError(ValueError):
  """A script could not be parsed or replayed."""


@dataclass(frozen=True)
class Step:
  """One line of a session script."""

  kind: str
  argument: str = ""
  value: Any = None
  line: int = 0

  def render(self) -> str:
    if self.kind == "configure":
      return f"CONFIGURE {self.argument} {_render_value(self.value)}"
    if self.kind == "touch":
      return f"TOUCH {self.value[0]} {self.value[1]}"
    if self.kind == "advance":
      return f"ADVANCE {self.value}"
    if self.kind == "reset":
      return "RESET"
    return f"{self.kind.upper()} {self.argument}".strip()


def _render_value(value: Any) -> str:
  if isinstance(value, bool):
    return "true" if value else "false"
  return str(value)


def _parse_configuration(key: str, raw: str, line: int) -> tuple[str, Any]:
  normalized = key.strip().lower()
  if normalized not in CONFIGURATION_KEYS:
    expected = ", ".join(CONFIGURATION_KEYS)
    raise SessionError(f"line {line}: unknown scenario key {key!r}; expected one of: {expected}")
  if normalized in BOOLEAN_KEYS:
    lowered = raw.strip().lower()
    if lowered not in ("true", "false", "1", "0"):
      raise SessionError(f"line {line}: {normalized} must be true or false")
    return normalized, lowered in ("true", "1")
  if normalized in INTEGER_KEYS:
    try:
      return normalized, int(raw.strip(), 10)
    except ValueError as error:
      raise SessionError(f"line {line}: {normalized} must be an integer") from error
  if normalized in FLOAT_KEYS:
    try:
      return normalized, float(raw.strip())
    except ValueError as error:
      raise SessionError(f"line {line}: {normalized} must be a number") from error
  if normalized == "host_mode":
    mode = raw.strip().upper()
    if mode not in MODE_ORDER:
      raise SessionError(f"line {line}: host_mode must be one of: {', '.join(MODE_ORDER)}")
    return normalized, mode
  if normalized == "outcome":
    outcome = raw.strip().upper()
    if outcome not in ("OK", "ERROR", "TIMEOUT"):
      raise SessionError(f"line {line}: outcome must be OK, ERROR, or TIMEOUT")
    return normalized, outcome
  # context and detail keep their spacing; only the separators are illegal.
  if any(character in raw for character in ("\t", "\r", "\n", "\0")):
    raise SessionError(f"line {line}: {normalized} cannot contain control separators")
  return normalized, raw


def parse_script(text: str) -> tuple[Step, ...]:
  """Parse a session script into validated steps."""
  steps: list[Step] = []
  for number, raw_line in enumerate(text.splitlines(), start=1):
    line = raw_line.split("#", 1)[0].strip() if not raw_line.strip().startswith("#") else ""
    if not line:
      continue
    keyword, _separator, remainder = line.partition(" ")
    keyword = keyword.upper()
    remainder = remainder.strip()

    if keyword == "TOUCH":
      parts = remainder.split()
      if len(parts) != 2:
        raise SessionError(f"line {number}: TOUCH needs an x and a y in panel pixels")
      try:
        x, y = (int(part, 10) for part in parts)
      except ValueError as error:
        raise SessionError(f"line {number}: TOUCH coordinates must be whole numbers") from error
      if not (0 <= x < DEVICE_SIZE and 0 <= y < DEVICE_SIZE):
        raise SessionError(f"line {number}: TOUCH must land inside 0..{DEVICE_SIZE - 1}")
      steps.append(Step("touch", value=(x, y), line=number))
    elif keyword == "ACTION":
      action = remainder.lower()
      if action not in ACTION_COMMANDS:
        expected = ", ".join(sorted(ACTION_COMMANDS))
        raise SessionError(f"line {number}: unknown action {remainder!r}; expected one of: {expected}")
      steps.append(Step("action", action, line=number))
    elif keyword == "ADVANCE":
      try:
        milliseconds = int(remainder, 10)
      except ValueError as error:
        raise SessionError(f"line {number}: ADVANCE needs a whole number of milliseconds") from error
      if not 0 <= milliseconds <= MAX_ADVANCE_MS:
        raise SessionError(f"line {number}: ADVANCE must be between 0 and {MAX_ADVANCE_MS} ms")
      steps.append(Step("advance", value=milliseconds, line=number))
    elif keyword == "CONFIGURE":
      key, _space, value = remainder.partition(" ")
      if not key:
        raise SessionError(f"line {number}: CONFIGURE needs a key and a value")
      normalized, parsed = _parse_configuration(key, value, number)
      steps.append(Step("configure", normalized, parsed, line=number))
    elif keyword == "RESET":
      steps.append(Step("reset", line=number))
    elif keyword == "SHOT":
      label = remainder or f"shot-{len(steps) + 1}"
      if not all(character.isalnum() or character in "-_" for character in label):
        raise SessionError(f"line {number}: SHOT label may only use letters, digits, - and _")
      steps.append(Step("shot", label, line=number))
    elif keyword == "NOTE":
      steps.append(Step("note", remainder, line=number))
    else:
      raise SessionError(f"line {number}: unknown command {keyword!r}")

    if len(steps) > MAX_STEPS:
      raise SessionError(f"a session script cannot exceed {MAX_STEPS} steps")
  return tuple(steps)


def format_script(steps: Iterable[Step], *, header: str | None = None) -> str:
  """Render steps back into a replayable script."""
  lines = []
  if header:
    lines.extend(f"# {line}" for line in header.splitlines())
    lines.append("")
  lines.extend(step.render() for step in steps)
  return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _text_box(command: dict[str, Any]) -> tuple[int, int, int, int] | None:
  layout = command.get("layout")
  if not isinstance(layout, dict):
    return None
  try:
    left = int(layout["left"])
    top = int(layout["top"])
    width = int(layout["width"])
    height = int(layout["height"])
  except (KeyError, TypeError, ValueError):
    return None
  return left, top, width, height


def _corner_outside_panel(left: int, top: int, width: int, height: int) -> bool:
  """True when any corner of the box falls outside the round panel."""
  for x in (left, left + width):
    for y in (top, top + height):
      distance = math.hypot(x - DEVICE_CENTER, y - DEVICE_CENTER)
      if distance > DEVICE_RADIUS:
        return True
  return False


def _boxes_overlap(
  first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> bool:
  left_a, top_a, width_a, height_a = first
  left_b, top_b, width_b, height_b = second
  return (
    left_a < left_b + width_b
    and left_b < left_a + width_a
    and top_a < top_b + height_b
    and top_b < top_a + height_a
  )


def _overlap_area(
  first: tuple[int, int, int, int], second: tuple[int, int, int, int]
) -> int:
  left_a, top_a, width_a, height_a = first
  left_b, top_b, width_b, height_b = second
  horizontal = min(left_a + width_a, left_b + width_b) - max(left_a, left_b)
  vertical = min(top_a + height_a, top_b + height_b) - max(top_a, top_b)
  return max(0, horizontal) * max(0, vertical)


def _opaque_shape_box(command: dict[str, Any]) -> tuple[int, int, int, int] | None:
  """Bounding box of a filled shape that hides whatever it is drawn over."""
  operation = command.get("op")
  try:
    if operation == "fillRoundRect":
      return int(command["x"]), int(command["y"]), int(command["w"]), int(command["h"])
    if operation == "fillCircle":
      x, y, radius = int(command["x"]), int(command["y"]), int(command["r"])
      return x - radius, y - radius, 2 * radius, 2 * radius
  except (KeyError, TypeError, ValueError):
    return None
  return None


# A finding is either something the panel cannot show at all, or something a
# person should look at. Only the first kind fails a run.
ERROR_KINDS = ("offscreen_text", "outside_round_panel", "overlapping_text", "unmeasured_text")
OCCLUSION_THRESHOLD = 0.2


def inspect_frame(frame: dict[str, Any]) -> list[dict[str, Any]]:
  """Report what the panel cannot actually show.

  Every finding is a geometric fact derived from the device's own text metrics,
  not a style preference.
  """
  commands = frame.get("commands")
  if not isinstance(commands, list):
    return []

  findings: list[dict[str, Any]] = []
  measured: list[tuple[int, str, tuple[int, int, int, int]]] = []
  for index, command in enumerate(commands):
    if not isinstance(command, dict) or command.get("op") != "drawString":
      continue
    text = str(command.get("text", ""))
    if not text.strip():
      continue
    box = _text_box(command)
    if box is None:
      findings.append(
        {
          "kind": "unmeasured_text",
          "severity": "error",
          "text": text,
          "detail": "no device layout published",
        }
      )
      continue
    left, top, width, height = box
    measured.append((index, text, box))

    if left < 0 or top < 0 or left + width > DEVICE_SIZE or top + height > DEVICE_SIZE:
      findings.append(
        {
          "kind": "offscreen_text",
          "severity": "error",
          "text": text,
          "box": [left, top, width, height],
          "detail": f"box leaves the {DEVICE_SIZE}x{DEVICE_SIZE} framebuffer",
        }
      )
    elif _corner_outside_panel(left, top, width, height):
      findings.append(
        {
          "kind": "outside_round_panel",
          "severity": "error",
          "text": text,
          "box": [left, top, width, height],
          "detail": "a corner falls outside the round AMOLED's visible circle",
        }
      )

  for position, (_index, text, box) in enumerate(measured):
    for _other_index, other_text, other_box in measured[position + 1 :]:
      if _boxes_overlap(box, other_box):
        findings.append(
          {
            "kind": "overlapping_text",
            "severity": "error",
            "text": text,
            "other": other_text,
            "box": list(box),
            "detail": "two strings share pixels",
          }
        )

  # A filled shape drawn after a string paints over it. That is how a toast is
  # supposed to work, and also how a panel loses a line nobody meant to hide.
  for index, command in enumerate(commands):
    if not isinstance(command, dict):
      continue
    shape = _opaque_shape_box(command)
    if shape is None:
      continue
    for text_index, text, box in measured:
      if text_index > index:
        continue
      area = box[2] * box[3]
      if area <= 0:
        continue
      covered = _overlap_area(box, shape) / area
      if covered >= OCCLUSION_THRESHOLD:
        findings.append(
          {
            "kind": "occluded_text",
            "severity": "notice",
            "text": text,
            "by": str(command.get("op")),
            "box": list(box),
            "detail": f"{covered:.0%} of the string is painted over by a later shape",
          }
        )
  return findings


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@dataclass
class Shot:
  """One captured frame plus what inspection found in it."""

  label: str
  index: int
  step_line: int
  screen: dict[str, Any]
  commands: list[Any]
  findings: list[dict[str, Any]]

  def to_json(self) -> dict[str, Any]:
    return {
      "label": self.label,
      "index": self.index,
      "line": self.step_line,
      "screen": self.screen,
      "commands": self.commands,
      "findings": self.findings,
    }


@dataclass
class SessionResult:
  firmware_id: str
  steps: tuple[Step, ...]
  shots: list[Shot] = field(default_factory=list)
  notes: list[str] = field(default_factory=list)

  @property
  def findings(self) -> list[dict[str, Any]]:
    return [finding for shot in self.shots for finding in shot.findings]

  @property
  def errors(self) -> list[dict[str, Any]]:
    return [finding for finding in self.findings if finding.get("severity") == "error"]

  def to_json(self) -> dict[str, Any]:
    return {
      "firmware": self.firmware_id,
      "steps": [
        {"line": step.line, "kind": step.kind, "argument": step.argument, "value": step.value}
        for step in self.steps
      ],
      "notes": list(self.notes),
      "shots": [shot.to_json() for shot in self.shots],
    }

  def golden(self) -> dict[str, Any]:
    """The deterministic projection a golden file locks."""
    return {
      "firmware": self.firmware_id,
      "shots": [
        {"label": shot.label, "screen": shot.screen, "commands": shot.commands}
        for shot in self.shots
      ],
    }


# Screen fields that describe what is on the panel. Everything else in the
# snapshot is host bookkeeping and does not belong in a golden.
GOLDEN_SCREEN_FIELDS = (
  "connected",
  "status",
  "battery_percent",
  "charging",
  "brightness",
  "sleeping",
  "time",
  "mode",
  "context",
  "detail",
  "focus_running",
  "elapsed_ms",
  "elapsed_text",
  "marks",
  "toast",
)


def _screen_projection(snapshot: dict[str, Any]) -> dict[str, Any]:
  screen = snapshot.get("screen")
  if not isinstance(screen, dict):
    return {}
  return {key: screen[key] for key in GOLDEN_SCREEN_FIELDS if key in screen}


def run_session(backend: Any, steps: Sequence[Step], *, firmware_id: str) -> SessionResult:
  """Replay steps against an already-started backend.

  Time is frozen for the whole replay, so the same script produces the same
  frames on a fast machine, a loaded machine, and in CI.
  """
  result = SessionResult(firmware_id=firmware_id, steps=tuple(steps))
  snapshot: dict[str, Any] = backend.freeze_time(True)

  for step in steps:
    if step.kind == "action":
      snapshot = backend.perform_action(step.argument)
    elif step.kind == "touch":
      snapshot = backend.touch(step.value[0], step.value[1])
    elif step.kind == "advance":
      snapshot = backend.advance(step.value)
    elif step.kind == "configure":
      snapshot = backend.configure({step.argument: step.value})
    elif step.kind == "reset":
      backend.reset()
      # A restart brings back a live clock; a replay must stay frozen.
      snapshot = backend.freeze_time(True)
    elif step.kind == "note":
      result.notes.append(step.argument)
      continue
    elif step.kind == "shot":
      frame = snapshot.get("frame")
      frame = frame if isinstance(frame, dict) else {}
      result.shots.append(
        Shot(
          label=step.argument,
          index=len(result.shots),
          step_line=step.line,
          screen=_screen_projection(snapshot),
          commands=list(frame.get("commands", [])),
          findings=inspect_frame(frame),
        )
      )
      continue

    error = snapshot.get("command_error")
    if error:
      raise SessionError(f"line {step.line}: {step.render()} was refused: {error}")
  return result


def load_script(path: str | Path) -> tuple[Step, ...]:
  text = Path(path).read_text(encoding="utf-8")
  try:
    return parse_script(text)
  except SessionError as error:
    raise SessionError(f"{path}: {error}") from error


def default_firmware_for(path: str | Path) -> str:
  """Infer the firmware from a scenario file name, defaulting to SOKKON."""
  stem = Path(path).stem
  if stem.startswith("stopwatch"):
    return "99_stopwatch"
  return DEFAULT_FIRMWARE_ID



class ScriptRecorder:
  """Append accepted UI commands to a replayable script file.

  Recording is the other half of replay: a session captured from a browser is
  the same text a test or an agent can run again, so "it looked wrong when I
  did this" becomes a file rather than a description.
  """

  def __init__(self, path: str | Path) -> None:
    self.path = Path(path)
    self.path.parent.mkdir(parents=True, exist_ok=True)
    self._shots = 0
    if not self.path.exists():
      self.path.write_text(
        "# Recorded simulator session. Replay it with:\n"
        f"#   python3 -m simulator.session {self.path}\n",
        encoding="utf-8",
      )

  def _append(self, line: str) -> None:
    with self.path.open("a", encoding="utf-8") as handle:
      handle.write(line + "\n")

  def record_touch(self, x: int, y: int) -> None:
    self._append(f"TOUCH {x} {y}")

  def record_action(self, action: str) -> None:
    if action in ACTION_COMMANDS:
      self._append(f"ACTION {action}")
      return
    if action == "reset":
      self._append("RESET")
      return
    # The UI's advance presets are already exact millisecond steps.
    from .backend import ADVANCE_COMMANDS

    milliseconds = ADVANCE_COMMANDS.get(action)
    if milliseconds is not None:
      self._append(f"ADVANCE {milliseconds}")

  def record_configuration(self, mapping: dict[str, Any]) -> None:
    for key in CONFIGURATION_KEYS:
      if key in mapping:
        self._append(f"CONFIGURE {key} {_render_value(mapping[key])}")

  def record_shot(self, label: str | None = None) -> str:
    self._shots += 1
    name = label or f"step-{self._shots:02d}"
    self._append(f"SHOT {name}")
    return name


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def _summarize(result: SessionResult, images: dict[str, Path]) -> str:
  lines = [f"session [{result.firmware_id}] {len(result.shots)} shot(s)"]
  for note in result.notes:
    lines.append(f"  note: {note}")
  for shot in result.shots:
    image = images.get(shot.label)
    suffix = f" -> {image}" if image else ""
    lines.append(
      f"  {shot.label}: {len(shot.commands)} draw command(s), "
      f"{len(shot.findings)} finding(s){suffix}"
    )
    for finding in shot.findings:
      severity = finding.get("severity", "error")
      marker = "!" if severity == "error" else "-"
      lines.append(
        f"      {marker} {finding['kind']}: {finding.get('text', '')!r} {finding['detail']}"
      )
  return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
  import argparse

  from .backend import SUPPORTED_FIRMWARE_IDS, BackendError, NativeSimulatorBackendManager

  parser = argparse.ArgumentParser(
    prog="python3 -m simulator.session",
    description="Replay a scripted simulator session and report what the panel shows.",
  )
  parser.add_argument("script", help="session script to replay")
  parser.add_argument(
    "--firmware",
    choices=SUPPORTED_FIRMWARE_IDS,
    help="production firmware to run (default: inferred from the script name)",
  )
  parser.add_argument("--out", help="directory for report.json and shot images")
  parser.add_argument(
    "--shots",
    dest="shots",
    action="store_true",
    help="render each SHOT to a PNG with a headless browser",
  )
  parser.add_argument("--no-shots", dest="shots", action="store_false")
  parser.set_defaults(shots=True)
  parser.add_argument("--json", action="store_true", help="print the full report as JSON")
  arguments = parser.parse_args(argv)

  try:
    steps = load_script(arguments.script)
  except (OSError, SessionError) as error:
    print(f"session error: {error}", file=sys.stderr)
    return 2

  firmware_id = arguments.firmware or default_firmware_for(arguments.script)
  try:
    with NativeSimulatorBackendManager(firmware_id=firmware_id) as backend:
      result = run_session(backend, steps, firmware_id=firmware_id)
  except (BackendError, SessionError) as error:
    print(f"session error: {error}", file=sys.stderr)
    return 1

  images: dict[str, Path] = {}
  output_directory = Path(arguments.out) if arguments.out else None
  if output_directory is not None:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "report.json").write_text(
      json.dumps(result.to_json(), ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
    )

  contact_sheet: Path | None = None
  if arguments.shots and output_directory is not None and result.shots:
    from .screenshot import Panel, ScreenshotError, capture_panels

    panels = [
      Panel(
        label=f"{shot.index:02d} {shot.label}",
        frame={"width": DEVICE_SIZE, "height": DEVICE_SIZE, "commands": shot.commands},
        screen=shot.screen,
      )
      for shot in result.shots
    ]
    try:
      contact_sheet = capture_panels(panels, output_directory / "contact-sheet.png")
    except ScreenshotError as error:
      print(f"session: no contact sheet: {error}", file=sys.stderr)
  elif arguments.shots and output_directory is None:
    print("session: --out is required to write shot images", file=sys.stderr)

  if arguments.json:
    print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
  else:
    print(_summarize(result, images))
    if contact_sheet is not None:
      print(f"  contact sheet: {contact_sheet}")
  return 1 if result.errors else 0


if __name__ == "__main__":
  raise SystemExit(main())


__all__ = [
  "BackendInputError",
  "DEVICE_RADIUS",
  "DEVICE_SIZE",
  "SessionError",
  "ScriptRecorder",
  "SessionResult",
  "Shot",
  "Step",
  "default_firmware_for",
  "format_script",
  "inspect_frame",
  "load_script",
  "parse_script",
  "run_session",
]
