"""Command-line entry point for ``python3 -m companion``."""

from __future__ import annotations

import argparse
import logging
import time
from typing import Sequence

from .actions import ActionHandler
from .binding import BindingError, load_binding, save_binding
from .config import ConfigError, load_config
from .serial_io import PortDetectionError, SerialError, SerialPort, detect_port
from .service import CompanionMemory, CompanionSession


LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="python3 -m companion",
    description="Bridge the M5Stack StopWatch Sokkon protocol to macOS.",
    epilog=(
      'Config JSON: {"capture_path":"~/Documents/Sokkon Inbox.md",'
      '"shortcuts":{"CAPTURE":"Name","FOCUS_TOGGLE":"Name","MODE_NEXT":"Name"}}'
    ),
  )
  parser.add_argument("--port", help="serial port; otherwise auto-detect /dev/cu.usbmodem*")
  parser.add_argument(
    "--pair",
    action="store_true",
    help="trust the attached Sokkon device without sending app context, then exit",
  )
  parser.add_argument("--binding", help="device binding path; defaults to ~/.config/sokkon/device.json")
  parser.add_argument(
    "--replace-binding",
    action="store_true",
    help="with --pair, replace a different existing device binding",
  )
  parser.add_argument("--once", action="store_true", help="send one state, handle queued input, then exit")
  parser.add_argument(
    "--dry-run",
    action="store_true",
    help="keep the USB protocol active but do not write captures or run Shortcuts",
  )
  parser.add_argument("--config", help="optional JSON configuration path")
  parser.add_argument("--verbose", action="store_true", help="show protocol and diagnostic logs")
  return parser


def main(argv: Sequence[str] | None = None) -> int:
  args = build_parser().parse_args(argv)
  if args.replace_binding and not args.pair:
    build_parser().error("--replace-binding requires --pair")
  logging.basicConfig(
    level=logging.DEBUG if args.verbose else logging.INFO,
    format="%(levelname)s %(message)s",
  )

  try:
    config = load_config(args.config)
  except ConfigError as error:
    LOGGER.error("configuration error: %s", error)
    return 2

  expected_device_id: str | None = None
  if not args.pair:
    try:
      expected_device_id = load_binding(args.binding)
    except BindingError as error:
      LOGGER.error("%s", error)
      return 2

  memory = CompanionMemory()
  while True:
    try:
      port = detect_port(args.port)
      LOGGER.info("connecting to %s at 115200 baud", port)
      with SerialPort(port) as serial_port:
        session = CompanionSession(
          serial_port,
          ActionHandler(config, dry_run=args.dry_run),
          memory=memory,
          expected_device_id=expected_device_id,
        )
        if args.pair:
          device_id, _session_id = session.handshake()
          binding_path = save_binding(
            device_id,
            args.binding,
            replace=args.replace_binding,
          )
          LOGGER.info("paired Sokkon device %s in %s", device_id, binding_path)
        else:
          session.run(once=args.once)
      if args.once or args.pair:
        return 0
    except KeyboardInterrupt:
      LOGGER.info("stopped")
      return 0
    except (BindingError, PortDetectionError, SerialError, OSError) as error:
      LOGGER.error("%s", error)
      if args.once or args.pair:
        return 1
      time.sleep(2.0)


if __name__ == "__main__":
  raise SystemExit(main())
