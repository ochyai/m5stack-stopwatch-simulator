#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package_root="$(cd "${script_dir}/.." && pwd)"
app_path="${package_root}/dist/M5Stack Simulator.app"
output_root="${package_root}/dist"
developer_id=""

usage() {
  cat <<'USAGE'
usage: build-dmg.sh [options]

Package an existing local M5Stack Simulator.app into a versioned DMG.
This script does not notarize, upload, or modify the source app.

Options:
  --app PATH                 App bundle to package
  --output DIRECTORY         DMG destination directory
  --developer-id <identity>  Sign the disk image with a Developer ID identity.
                             Gatekeeper reads the image's own signature when a
                             download is opened, so a distributed DMG needs one
                             even though the app inside is already signed.
  -h, --help                 Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      app_path="$2"
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      output_root="$2"
      shift 2
      ;;
    --developer-id)
      [[ $# -ge 2 ]] || { echo "--developer-id needs an identity" >&2; exit 2; }
      developer_id="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for command in hdiutil lipo paste shasum sort tr; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "required command not found: ${command}" >&2
    exit 1
  }
done

[[ -d "${app_path}" && -f "${app_path}/Contents/Info.plist" ]] || {
  echo "app bundle is missing or invalid: ${app_path}" >&2
  exit 1
}
executable_name="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "${app_path}/Contents/Info.plist")"
version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "${app_path}/Contents/Info.plist")"
executable_path="${app_path}/Contents/MacOS/${executable_name}"
[[ -x "${executable_path}" ]] || {
  echo "app executable is missing: ${executable_path}" >&2
  exit 1
}
[[ "${version}" =~ ^[0-9]+([.][0-9]+){1,2}$ ]] || {
  echo "app version is not safe for a DMG filename: ${version}" >&2
  exit 1
}

canonical_architectures() {
  lipo -archs "$1" | tr ' ' '\n' | LC_ALL=C sort | paste -sd ' ' -
}

architectures="$(canonical_architectures "${executable_path}")"
for runner_name in sokkon-native stopwatch-native; do
  runner_path="${app_path}/Contents/Resources/Native/${runner_name}"
  [[ -x "${runner_path}" ]] || {
    echo "packaged native runner is missing: ${runner_path}" >&2
    exit 1
  }
  runner_architectures="$(canonical_architectures "${runner_path}")"
  [[ "${runner_architectures}" == "${architectures}" ]] || {
    echo "architecture mismatch: ${runner_name} has [${runner_architectures}], app has [${architectures}]" >&2
    exit 1
  }
done
case "${architectures}" in
  arm64|x86_64)
    architecture_label="${architectures}"
    ;;
  "arm64 x86_64")
    architecture_label="universal"
    ;;
  *)
    echo "unsupported executable architecture list: ${architectures}" >&2
    exit 1
    ;;
esac

mkdir -p "${output_root}"
output_root="$(cd "${output_root}" && pwd)"
# "-local" marks an image that only this Mac can open. A Developer ID signed
# image is meant to travel, so it does not carry that warning in its name.
if [[ -n "${developer_id}" ]]; then
  base_name="M5Stack-Simulator-${version}-${architecture_label}"
else
  base_name="M5Stack-Simulator-${version}-${architecture_label}-local"
fi
dmg_path="${output_root}/${base_name}.dmg"
checksum_path="${dmg_path}.sha256"
staging_root="$(mktemp -d "${output_root}/.M5StackSimulatorDMG.XXXXXX")"
disk_root="${staging_root}/disk"
temporary_dmg="${staging_root}/${base_name}.dmg"
trap 'rm -rf "${staging_root}"' EXIT

mkdir -p "${disk_root}"
/usr/bin/ditto "${app_path}" "${disk_root}/M5Stack Simulator.app"
ln -s /Applications "${disk_root}/Applications"

hdiutil create \
  -quiet \
  -volname "M5Stack Simulator ${version}" \
  -srcfolder "${disk_root}" \
  -format UDZO \
  -ov \
  "${temporary_dmg}"
hdiutil imageinfo "${temporary_dmg}" >/dev/null

# Replace only this exact versioned artifact. Other releases and caller files
# in the output directory remain untouched.
rm -f "${dmg_path}" "${checksum_path}"
mv "${temporary_dmg}" "${dmg_path}"

if [[ -n "${developer_id}" ]]; then
  codesign --force --timestamp --sign "${developer_id}" "${dmg_path}"
  codesign --verify --strict --verbose=2 "${dmg_path}"
fi

(
  cd "${output_root}"
  shasum -a 256 "$(basename "${dmg_path}")" >"$(basename "${checksum_path}")"
)
rm -rf "${staging_root}"
trap - EXIT

echo "Built ${dmg_path}"
echo "Checksum ${checksum_path}"
# Report what the packaged app is actually signed with rather than assuming.
# Read the description into a variable first: piping into `grep -q` lets grep
# exit early, and the SIGPIPE that kills codesign would fail the whole pipeline
# under `set -o pipefail`.
signature_description="$(codesign -dv --verbose=4 "${app_path}" 2>&1 || true)"
if [[ "${signature_description}" == *"Authority=Developer ID Application"* ]]; then
  echo "Distribution status: Developer ID signed; notarize next with scripts/notarize-dmg.sh"
else
  echo "Distribution status: local/unsigned; Developer ID and notarization still required"
fi
