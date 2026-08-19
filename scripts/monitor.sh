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
  environment="$(sed -nE 's/^[[:space:]]*default_envs[[:space:]]*=[[:space:]]*([^,[:space:]]+).*$/\1/p' platformio.ini | head -n 1)"
fi
if [[ -z "${environment}" ]]; then
  environments=()
  while IFS= read -r item; do
    environments+=("${item}")
  done < <(sed -nE 's/^[[:space:]]*\[env:([^]]+)\][[:space:]]*$/\1/p' platformio.ini)

  if [[ "${#environments[@]}" -eq 1 ]]; then
    environment="${environments[0]}"
  elif [[ "${#environments[@]}" -gt 1 ]]; then
    printf 'error: choose a PlatformIO environment with ENV=name or as the first argument\n' >&2
    printf 'Available environments: %s\n' "${environments[*]}" >&2
    exit 1
  fi
fi

port="$("${script_dir}/detect-port.sh")"
monitor_args=(device monitor --port "${port}")
if [[ -n "${environment}" ]]; then
  monitor_args+=(--environment "${environment}")
else
  monitor_args+=(--baud "${MONITOR_BAUD:-115200}")
fi

exec pio "${monitor_args[@]}"
