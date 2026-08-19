#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "${repo_root}"

if ! command -v pio >/dev/null 2>&1; then
  printf 'error: PlatformIO CLI (pio) is not available on PATH\n' >&2
  exit 1
fi

if [[ "$#" -gt 1 ]]; then
  printf 'usage: %s [platformio-environment]\n' "${0##*/}" >&2
  exit 2
fi

environment="${1:-${PIO_ENV:-}}"
if [[ -z "${environment}" ]]; then
  printf 'error: flashing requires an explicit environment (for example ENV=00_smoke)\n' >&2
  printf 'usage: make flash ENV=00_smoke PORT=/dev/cu.usbmodemXXXX\n' >&2
  exit 2
fi
if [[ "${environment}" == "native" ]]; then
  printf 'error: native is a host-test environment and cannot be flashed\n' >&2
  exit 2
fi
if [[ -z "${PORT:-}" ]]; then
  printf 'error: flashing requires an explicit PORT to avoid selecting another USB device\n' >&2
  printf 'usage: make flash ENV=%s PORT=/dev/cu.usbmodemXXXX\n' "${environment}" >&2
  exit 2
fi

port="$("${script_dir}/detect-port.sh")"
printf 'Flashing environment %s to %s. This writes device flash.\n' "${environment}" "${port}" >&2
exec pio run --environment "${environment}" --target upload --upload-port "${port}"
