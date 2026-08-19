"""CLI for ``python3 -m simulator``."""

from __future__ import annotations

import argparse
import ipaddress
import socket
import sys
from typing import Sequence
import webbrowser

from .backend import (
  BackendError,
  DEFAULT_FIRMWARE_ID,
  SUPPORTED_FIRMWARE_IDS,
  NativeSimulatorBackendManager,
)
from .server import DEFAULT_HOST, DEFAULT_PORT, create_server


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    prog="python3 -m simulator",
    description="Run a compiler-driven M5Stack StopWatch firmware simulator on this Mac.",
  )
  parser.add_argument(
    "--firmware",
    choices=SUPPORTED_FIRMWARE_IDS,
    default=DEFAULT_FIRMWARE_ID,
    help=f"production firmware to compile and run (default: {DEFAULT_FIRMWARE_ID})",
  )
  parser.add_argument("--host", default=DEFAULT_HOST, help="bind host (default: 127.0.0.1)")
  parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port (default: 8765)")
  parser.add_argument(
    "--allow-remote",
    action="store_true",
    help="allow a non-loopback bind; exposes simulator controls to the network",
  )
  browser = parser.add_mutually_exclusive_group()
  browser.add_argument("--open", dest="open_browser", action="store_true", help="open the UI")
  browser.add_argument("--no-open", dest="open_browser", action="store_false", help="do not open the UI")
  parser.set_defaults(open_browser=False)
  return parser


def host_is_loopback(host: str) -> bool:
  """Resolve a bind host and require every result to be loopback."""
  try:
    literal = ipaddress.ip_address(host)
  except ValueError:
    try:
      addresses = {
        item[4][0]
        for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
      }
    except socket.gaierror:
      return False
    if not addresses:
      return False
    try:
      return all(ipaddress.ip_address(address).is_loopback for address in addresses)
    except ValueError:
      return False
  return literal.is_loopback


def browser_url(host: str, port: int) -> str:
  display_host = host
  if host == "0.0.0.0":
    display_host = "127.0.0.1"
  elif host == "::":
    display_host = "::1"
  if ":" in display_host and not display_host.startswith("["):
    display_host = f"[{display_host}]"
  return f"http://{display_host}:{port}/"


def main(argv: Sequence[str] | None = None) -> int:
  parser = build_parser()
  args = parser.parse_args(argv)
  if not 0 <= args.port <= 65_535:
    parser.error("--port must be between 0 and 65535")
  if not args.allow_remote and not host_is_loopback(args.host):
    parser.error("non-loopback --host requires explicit --allow-remote")
  if args.allow_remote and not host_is_loopback(args.host):
    print("WARNING: simulator controls are exposed beyond this Mac", file=sys.stderr)

  try:
    with NativeSimulatorBackendManager(firmware_id=args.firmware) as backend:
      server = create_server(backend, host=args.host, port=args.port)
      try:
        bound_port = server.server_address[1]
        url = browser_url(args.host, bound_port)
        print(f"M5Stack simulator [{args.firmware}]: {url}", flush=True)
        if args.open_browser:
          webbrowser.open(url)
        server.serve_forever(poll_interval=0.1)
      except KeyboardInterrupt:
        print(f"\nM5Stack simulator [{args.firmware}] stopped", file=sys.stderr)
      finally:
        server.server_close()
  except (BackendError, OSError, ValueError) as error:
    print(f"simulator error: {error}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
