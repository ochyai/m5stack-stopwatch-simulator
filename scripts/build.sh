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
if [[ "${environment}" == "--all" ]]; then
  environments=()
  has_native=false
  while IFS= read -r item; do
    if [[ "${item}" == "native" ]]; then
      has_native=true
    else
      environments+=("${item}")
    fi
  done < <(sed -nE 's/^[[:space:]]*\[env:([^]]+)\][[:space:]]*$/\1/p' platformio.ini)

  if [[ "${#environments[@]}" -eq 0 && "${has_native}" != true ]]; then
    printf 'error: no build or test environments found in platformio.ini\n' >&2
    exit 1
  fi

  if [[ "${#environments[@]}" -gt 0 ]]; then
    pio_args=(run)
    for item in "${environments[@]}"; do
      pio_args+=(--environment "${item}")
    done
    pio "${pio_args[@]}"
  fi

  if [[ "${has_native}" == true ]]; then
    exec pio test --environment native
  fi
  exit 0
fi

if [[ -n "${environment}" ]]; then
  exec pio run --environment "${environment}"
fi

exec pio run
