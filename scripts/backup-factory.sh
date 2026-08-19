#!/usr/bin/env bash
set -euo pipefail
umask 077

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
cd "${repo_root}"

if ! command -v uvx >/dev/null 2>&1; then
  printf 'error: uvx is required for the pinned esptool backup environment\n' >&2
  printf 'Install uv from https://docs.astral.sh/uv/ and retry.\n' >&2
  exit 1
fi

port="$("${script_dir}/detect-port.sh")"
baud="${ESPTOOL_BAUD:-460800}"
backup_dir="${repo_root}/backups"
timestamp="$(date -u '+%Y%m%dT%H%M%SZ')"
image="${backup_dir}/factory-flash-${timestamp}.bin"
partial_image="${image}.partial"
checksum="${image}.sha256"
chunk_dir="${backup_dir}/.factory-flash-${timestamp}.chunks"
chunk_size=$((0x100000))
chunk_count=16
esptool=(uvx --python 3.11 --from "esptool==4.9.0" esptool.py)

cleanup() {
  rm -f "${partial_image}"
  for ((index = 0; index < chunk_count; ++index)); do
    printf -v chunk '%s/chunk-%02d.bin' "${chunk_dir}" "${index}"
    rm -f "${chunk}"
  done
  rmdir "${chunk_dir}" 2>/dev/null || true
}

mkdir -p "${backup_dir}" "${chunk_dir}"
chmod 700 "${backup_dir}" "${chunk_dir}"
trap cleanup EXIT INT TERM

printf 'Reading 16 MiB from %s at %s baud...\n' "${port}" "${baud}"
printf 'Using 16 x 1 MiB chunks so a transient USB error can be retried.\n'
for ((index = 0; index < chunk_count; ++index)); do
  offset=$((index * chunk_size))
  printf -v offset_hex '0x%X' "${offset}"
  printf -v chunk '%s/chunk-%02d.bin' "${chunk_dir}" "${index}"
  printf '[%02d/%02d] Reading %s...\n' "$((index + 1))" "${chunk_count}" "${offset_hex}"

  for attempt in 1 2 3; do
    if "${esptool[@]}" \
      --chip esp32s3 \
      --port "${port}" \
      --baud "${baud}" \
      --no-stub \
      read_flash --flash_size 16MB --no-progress \
      "${offset_hex}" "${chunk_size}" "${chunk}"; then
      break
    fi
    rm -f "${chunk}"
    if [[ "${attempt}" -eq 3 ]]; then
      printf 'error: chunk %s failed after 3 attempts\n' "${offset_hex}" >&2
      exit 1
    fi
    printf 'Retrying chunk %s (%d/3)...\n' "${offset_hex}" "$((attempt + 1))" >&2
    sleep 1
  done
done

: >"${partial_image}"
for ((index = 0; index < chunk_count; ++index)); do
  printf -v chunk '%s/chunk-%02d.bin' "${chunk_dir}" "${index}"
  cat "${chunk}" >>"${partial_image}"
done

actual_size="$(wc -c <"${partial_image}" | tr -d '[:space:]')"
if [[ "${actual_size}" != "16777216" ]]; then
  printf 'error: backup size is %s bytes, expected 16777216\n' "${actual_size}" >&2
  exit 1
fi
mv "${partial_image}" "${image}"

if command -v shasum >/dev/null 2>&1; then
  digest="$(shasum -a 256 "${image}" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  digest="$(sha256sum "${image}" | awk '{print $1}')"
else
  printf 'error: neither shasum nor sha256sum is available\n' >&2
  exit 1
fi

printf '%s  %s\n' "${digest}" "$(basename "${image}")" >"${checksum}"
cleanup
trap - EXIT INT TERM

printf 'Backup: %s\n' "${image}"
printf 'SHA-256: %s\n' "${digest}"
printf 'Checksum file: %s\n' "${checksum}"
