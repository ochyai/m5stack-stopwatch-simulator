#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "${repo_root}"

if ! command -v pio >/dev/null 2>&1; then
  printf 'error: PlatformIO CLI (pio) is not available on PATH\n' >&2
  exit 1
fi

port="$("${script_dir}/detect-port.sh")"
esptool=(pio pkg exec --package "tool-esptoolpy@1.40501.0" -- esptool.py)

printf 'Using serial port: %s\n' "${port}"
printf '\n== Chip ID ==\n'
"${esptool[@]}" --port "${port}" chip_id
printf '\n== Flash ID ==\n'
"${esptool[@]}" --port "${port}" flash_id
printf '\n== Security information ==\n'
"${esptool[@]}" --port "${port}" get_security_info
