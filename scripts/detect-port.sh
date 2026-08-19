#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${PORT:-}" ]]; then
  if [[ ! -e "${PORT}" ]]; then
    printf 'error: PORT does not exist: %s\n' "${PORT}" >&2
    exit 1
  fi
  printf '%s\n' "${PORT}"
  exit 0
fi

shopt -s nullglob
ports=(/dev/cu.usbmodem*)
shopt -u nullglob

case "${#ports[@]}" in
  0)
    printf 'error: no M5Stack serial port found at /dev/cu.usbmodem*\n' >&2
    printf 'Connect the device, or set PORT=/dev/cu.<device> explicitly.\n' >&2
    exit 1
    ;;
  1)
    printf '%s\n' "${ports[0]}"
    ;;
  *)
    printf 'error: multiple /dev/cu.usbmodem* ports found; set PORT explicitly:\n' >&2
    printf '  %s\n' "${ports[@]}" >&2
    exit 1
    ;;
esac
