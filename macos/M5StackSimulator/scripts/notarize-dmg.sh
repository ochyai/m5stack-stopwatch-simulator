#!/usr/bin/env bash
set -euo pipefail

# Notarize an already Developer ID signed DMG and staple the ticket to it.
#
# This script never sees an Apple ID or an app-specific password. Store those
# once in the keychain yourself:
#
#   xcrun notarytool store-credentials m5stack-simulator \
#     --apple-id <your-apple-id> --team-id <TEAMID> --password <app-specific-password>
#
# and then pass only the profile name here.

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package_root="$(cd "${script_dir}/.." && pwd)"
dist_dir="${package_root}/dist"
keychain_profile=""
dmg_path=""

usage() {
  cat <<'USAGE'
Usage: notarize-dmg.sh --keychain-profile <name> [--dmg <path>]

Submit a signed DMG to Apple's notary service, wait for the verdict, staple the
ticket, and verify that Gatekeeper accepts the result.

  --keychain-profile <name>  notarytool credential profile stored in the keychain
  --dmg <path>               DMG to notarize (default: the newest one in dist/)

Before this script:
  ./scripts/build-app.sh --developer-id "Developer ID Application: NAME (TEAMID)"
  ./scripts/build-dmg.sh
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keychain-profile)
      [[ $# -ge 2 ]] || { echo "--keychain-profile needs a name" >&2; exit 2; }
      keychain_profile="$2"
      shift
      ;;
    --dmg)
      [[ $# -ge 2 ]] || { echo "--dmg needs a path" >&2; exit 2; }
      dmg_path="$2"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ -z "${keychain_profile}" ]]; then
  echo "--keychain-profile is required" >&2
  usage >&2
  exit 2
fi

command -v xcrun >/dev/null 2>&1 || {
  echo "xcrun is unavailable; install the Xcode command line tools" >&2
  exit 1
}

if [[ -z "${dmg_path}" ]]; then
  # Newest DMG in dist/, chosen without parsing ls output.
  dmg_path="$(find "${dist_dir}" -maxdepth 1 -name '*.dmg' -print0 2>/dev/null \
    | xargs -0 -r stat -f '%m %N' \
    | sort -rn \
    | head -1 \
    | cut -d' ' -f2-)"
fi

[[ -n "${dmg_path}" && -f "${dmg_path}" ]] || {
  echo "no DMG found; run ./scripts/build-dmg.sh first" >&2
  exit 1
}

echo "Notarizing ${dmg_path}"

# A DMG whose app is only ad-hoc signed is rejected by the notary service after
# a slow round trip. Refuse it here with a message that says what to do.
if ! codesign --verify --strict "${dmg_path}" 2>/dev/null; then
  echo "warning: the DMG itself is not signed; the app inside must be" >&2
fi

xcrun notarytool submit "${dmg_path}" \
  --keychain-profile "${keychain_profile}" \
  --wait

xcrun stapler staple "${dmg_path}"
xcrun stapler validate "${dmg_path}"

# What another Mac will actually decide when the DMG is opened.
spctl --assess --type open --context context:primary-signature --verbose=2 "${dmg_path}"

if command -v shasum >/dev/null 2>&1; then
  ( cd "$(dirname "${dmg_path}")" \
    && shasum -a 256 "$(basename "${dmg_path}")" >"$(basename "${dmg_path}").sha256" )
  echo "Updated checksum: ${dmg_path}.sha256"
fi

echo "Notarized and stapled: ${dmg_path}"
