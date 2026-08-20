#!/usr/bin/env bash
set -euo pipefail

# Notarize a Developer ID signed release and staple both artifacts.
#
# The order matters. A ticket stapled to the disk image does not travel with
# the app a person drags out of it, so that copy has to reach Apple over the
# network the first time it runs. Notarize the app first and staple the bundle,
# then build the image around the already-stapled app and notarize that. Both
# then launch with no network at all.
#
# This script never sees an Apple ID or an app-specific password. Store those
# once in the keychain yourself:
#
#   xcrun notarytool store-credentials <profile> \
#     --apple-id <your-apple-id> --team-id <TEAMID> --password <app-specific-password>

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package_root="$(cd "${script_dir}/.." && pwd)"
dist_dir="${package_root}/dist"
app_path="${dist_dir}/M5Stack Simulator.app"
keychain_profile=""
developer_id=""

usage() {
  cat <<'USAGE'
Usage: notarize-release.sh --keychain-profile <name> [--developer-id <identity>] [--app <path>]

Notarize the built app, staple it, rebuild the DMG around the stapled bundle,
notarize the image, and verify what Gatekeeper will decide for a download.

  --keychain-profile <name>  notarytool credential profile stored in the keychain
  --developer-id <identity>  identity used to sign the rebuilt disk image
                             (defaults to the identity already on the app)
  --app <path>               app bundle to release (default: dist/M5Stack Simulator.app)

Before this script:
  ./scripts/build-app.sh --developer-id "Developer ID Application: NAME (TEAMID)"
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --keychain-profile)
      [[ $# -ge 2 ]] || { echo "--keychain-profile needs a name" >&2; exit 2; }
      keychain_profile="$2"
      shift 2
      ;;
    --developer-id)
      [[ $# -ge 2 ]] || { echo "--developer-id needs an identity" >&2; exit 2; }
      developer_id="$2"
      shift 2
      ;;
    --app)
      [[ $# -ge 2 ]] || { echo "--app needs a path" >&2; exit 2; }
      app_path="$2"
      shift 2
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
[[ -d "${app_path}" ]] || {
  echo "app bundle not found: ${app_path}" >&2
  echo "run ./scripts/build-app.sh --developer-id \"Developer ID Application: ...\" first" >&2
  exit 1
}

# The notary service rejects anything that is not Developer ID signed, after a
# slow round trip. Establish that here instead.
signature_description="$(codesign -dv --verbose=4 "${app_path}" 2>&1 || true)"
if [[ "${signature_description}" != *"Authority=Developer ID Application"* ]]; then
  echo "the app is not Developer ID signed; rebuild it with build-app.sh --developer-id" >&2
  exit 1
fi
if [[ -z "${developer_id}" ]]; then
  developer_id="$(printf '%s\n' "${signature_description}" \
    | sed -n 's/^Authority=\(Developer ID Application:.*\)$/\1/p' \
    | head -1)"
fi
[[ -n "${developer_id}" ]] || {
  echo "could not read the signing identity from the app" >&2
  exit 1
}

workspace="$(mktemp -d "${dist_dir}/.notarize.XXXXXX")"
trap 'rm -rf "${workspace}"' EXIT

echo "== 1/3 notarizing the app =="
app_archive="${workspace}/app.zip"
/usr/bin/ditto -c -k --keepParent "${app_path}" "${app_archive}"
xcrun notarytool submit "${app_archive}" --keychain-profile "${keychain_profile}" --wait
xcrun stapler staple "${app_path}"

echo "== 2/3 rebuilding the disk image around the stapled app =="
"${script_dir}/build-dmg.sh" --app "${app_path}" --developer-id "${developer_id}"

dmg_path="$(find "${dist_dir}" -maxdepth 1 -name '*.dmg' -print0 2>/dev/null \
  | xargs -0 -r stat -f '%m %N' 2>/dev/null \
  | sort -rn || true)"
dmg_path="${dmg_path%%$'\n'*}"
dmg_path="${dmg_path#* }"
[[ -n "${dmg_path}" && -f "${dmg_path}" ]] || {
  echo "the disk image was not rebuilt" >&2
  exit 1
}

echo "== 3/3 notarizing ${dmg_path##*/} =="
xcrun notarytool submit "${dmg_path}" --keychain-profile "${keychain_profile}" --wait
xcrun stapler staple "${dmg_path}"

echo "== verification =="
xcrun stapler validate "${app_path}"
xcrun stapler validate "${dmg_path}"
# What another Mac decides for a download, and for the copy dragged out of it.
spctl --assess --type open --context context:primary-signature --verbose=2 "${dmg_path}"
spctl --assess --type execute --verbose=2 "${app_path}"

if command -v shasum >/dev/null 2>&1; then
  ( cd "$(dirname "${dmg_path}")" \
    && shasum -a 256 "$(basename "${dmg_path}")" >"$(basename "${dmg_path}").sha256" )
  echo "Updated checksum: ${dmg_path}.sha256"
fi

echo "Released: ${dmg_path}"
