#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
package_root="$(cd "${script_dir}/.." && pwd)"
repository_root="$(cd "${package_root}/../.." && pwd)"
workbench_root="${repository_root}/simulator/workbench"
workbench_output="${workbench_root}/dist/client"
configuration="release"
version="0.1.0"
build_number="1"
run_tests=1
install_dependencies=1
adhoc_sign=0
developer_id=""
output_root="${package_root}/dist"

usage() {
  cat <<'USAGE'
usage: build-app.sh [options]

Build an unsigned, self-contained M5Stack Simulator.app for the current Mac.

Options:
  --configuration debug|release  Swift build configuration (default: release)
  --output DIRECTORY             Parent directory for the .app bundle
  --version X.Y.Z                CFBundleShortVersionString (default: 0.1.0)
  --build-number INTEGER         CFBundleVersion (default: 1)
  --skip-tests                   Do not run the Swift bridge tests
  --skip-dependency-install      Reuse workbench node_modules instead of npm ci
  --adhoc-sign                   Apply a local ad-hoc signature (never Developer ID)
  --developer-id <identity>      Sign with a Developer ID Application identity and the
                                 hardened runtime, ready for notarization
  -h, --help                     Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --configuration)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      configuration="$2"
      shift 2
      ;;
    --output)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      output_root="$2"
      shift 2
      ;;
    --version)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      version="$2"
      shift 2
      ;;
    --build-number)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      build_number="$2"
      shift 2
      ;;
    --skip-tests)
      run_tests=0
      shift
      ;;
    --skip-dependency-install)
      install_dependencies=0
      shift
      ;;
    --developer-id)
      [[ $# -ge 2 ]] || { echo "--developer-id needs an identity" >&2; exit 2; }
      developer_id="$2"
      shift 2
      ;;
    --adhoc-sign)
      adhoc_sign=1
      shift
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

[[ "${configuration}" == "debug" || "${configuration}" == "release" ]] || {
  echo "configuration must be debug or release" >&2
  exit 2
}
[[ "${version}" =~ ^[0-9]+([.][0-9]+){1,2}$ ]] || {
  echo "version must contain two or three numeric components" >&2
  exit 2
}
[[ "${build_number}" =~ ^[1-9][0-9]*$ ]] || {
  echo "build number must be a positive integer" >&2
  exit 2
}

for command in npm swift plutil sips iconutil; do
  command -v "${command}" >/dev/null 2>&1 || {
    echo "required command not found: ${command}" >&2
    exit 1
  }
done

if [[ ${install_dependencies} -eq 1 ]]; then
  npm ci --prefix "${workbench_root}"
elif [[ ! -d "${workbench_root}/node_modules" ]]; then
  echo "workbench node_modules is missing; remove --skip-dependency-install" >&2
  exit 1
fi
npm run build --prefix "${workbench_root}"
[[ -f "${workbench_output}/index.html" ]] || {
  echo "workbench build did not create ${workbench_output}/index.html" >&2
  exit 1
}
npm run test:sites --prefix "${workbench_root}"

MACOSX_DEPLOYMENT_TARGET=13.0 "${repository_root}/scripts/build-simulator.sh" --firmware 10_sokkon
MACOSX_DEPLOYMENT_TARGET=13.0 "${repository_root}/scripts/build-simulator.sh" --firmware 99_stopwatch

verify_runner() {
  local executable="$1"
  local expected_id="$2"
  local snapshot
  snapshot="$(printf 'SNAPSHOT\n' | "${executable}")"
  [[ "${snapshot}" == *"\"id\":\"${expected_id}\""* ]] || {
    echo "native runner identity check failed for ${expected_id}" >&2
    exit 1
  }
}
verify_runner "${repository_root}/.simulator/sokkon-native" "10_sokkon"
verify_runner "${repository_root}/.simulator/stopwatch-native" "99_stopwatch"

swift_options=(--disable-sandbox --package-path "${package_root}" --configuration "${configuration}")
if [[ ${run_tests} -eq 1 ]]; then
  swift test "${swift_options[@]}"
fi
swift build "${swift_options[@]}" --product M5StackSimulator
binary_root="$(swift build "${swift_options[@]}" --show-bin-path)"
swift_executable="${binary_root}/M5StackSimulator"
[[ -x "${swift_executable}" ]] || {
  echo "Swift executable is missing: ${swift_executable}" >&2
  exit 1
}

mkdir -p "${output_root}"
output_root="$(cd "${output_root}" && pwd)"
app_path="${output_root}/M5Stack Simulator.app"
staging_root="$(mktemp -d "${output_root}/.M5StackSimulator.XXXXXX")"
staging_app="${staging_root}/M5Stack Simulator.app"
trap 'rm -rf "${staging_root}"' EXIT

mkdir -p \
  "${staging_app}/Contents/MacOS" \
  "${staging_app}/Contents/Resources/Native" \
  "${staging_app}/Contents/Resources/Web"

icon_source="${package_root}/Resources/AppIconSource.png"
[[ -f "${icon_source}" ]] || {
  echo "app icon source is missing: ${icon_source}" >&2
  exit 1
}
iconset="${staging_root}/AppIcon.iconset"
mkdir -p "${iconset}"
while read -r filename size; do
  sips -z "${size}" "${size}" "${icon_source}" --out "${iconset}/${filename}" >/dev/null
done <<'ICON_SIZES'
icon_16x16.png 16
icon_16x16@2x.png 32
icon_32x32.png 32
icon_32x32@2x.png 64
icon_128x128.png 128
icon_128x128@2x.png 256
icon_256x256.png 256
icon_256x256@2x.png 512
icon_512x512.png 512
icon_512x512@2x.png 1024
ICON_SIZES
icon_output="${staging_app}/Contents/Resources/AppIcon.icns"
if ! iconutil -c icns "${iconset}" -o "${icon_output}"; then
  # iconutil is denied by some automation sandboxes on macOS 26 even when the
  # standard iconset is valid. Keep the normal Apple tool as the primary path,
  # then assemble the same modern PNG ICNS chunks without external packages.
  echo "iconutil could not convert the iconset; using deterministic ICNS fallback" >&2
  swift "${package_root}/scripts/make-icns.swift" "${iconset}" "${icon_output}"
fi

cp "${swift_executable}" "${staging_app}/Contents/MacOS/M5StackSimulator"
cp "${package_root}/Config/Info.plist" "${staging_app}/Contents/Info.plist"
cp "${repository_root}/.simulator/sokkon-native" "${staging_app}/Contents/Resources/Native/sokkon-native"
cp "${repository_root}/.simulator/stopwatch-native" "${staging_app}/Contents/Resources/Native/stopwatch-native"
/usr/bin/ditto "${workbench_output}" "${staging_app}/Contents/Resources/Web"
chmod 755 \
  "${staging_app}/Contents/MacOS/M5StackSimulator" \
  "${staging_app}/Contents/Resources/Native/sokkon-native" \
  "${staging_app}/Contents/Resources/Native/stopwatch-native"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${version}" "${staging_app}/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion ${build_number}" "${staging_app}/Contents/Info.plist"
plutil -lint "${staging_app}/Contents/Info.plist"
[[ -f "${staging_app}/Contents/Resources/Web/index.html" ]] || {
  echo "packaged Workbench index.html is missing" >&2
  exit 1
}
[[ -s "${staging_app}/Contents/Resources/AppIcon.icns" ]] || {
  echo "packaged AppIcon.icns is missing" >&2
  exit 1
}

if [[ -n "${developer_id}" && ${adhoc_sign} -eq 1 ]]; then
  echo "--developer-id and --adhoc-sign are mutually exclusive" >&2
  exit 2
fi

if [[ -n "${developer_id}" ]]; then
  command -v codesign >/dev/null 2>&1 || {
    echo "codesign is unavailable" >&2
    exit 1
  }
  # Sign inside out: the hardened runtime refuses to launch a helper the outer
  # signature does not already cover.
  for binary in \
    "${staging_app}/Contents/Resources/Native/sokkon-native" \
    "${staging_app}/Contents/Resources/Native/stopwatch-native" \
    "${staging_app}/Contents/MacOS/M5StackSimulator"; do
    codesign --force --options runtime --timestamp --sign "${developer_id}" "${binary}"
  done
  codesign --force --options runtime --timestamp --sign "${developer_id}" "${staging_app}"
  codesign --verify --deep --strict --verbose=2 "${staging_app}"
elif [[ ${adhoc_sign} -eq 1 ]]; then
  command -v codesign >/dev/null 2>&1 || {
    echo "codesign is unavailable" >&2
    exit 1
  }
  codesign --force --sign - --timestamp=none "${staging_app}/Contents/Resources/Native/sokkon-native"
  codesign --force --sign - --timestamp=none "${staging_app}/Contents/Resources/Native/stopwatch-native"
  codesign --force --sign - --timestamp=none "${staging_app}/Contents/MacOS/M5StackSimulator"
  codesign --force --sign - --timestamp=none "${staging_app}"
fi

# Only this script's generated bundle is replaced. Source directories and any
# caller-supplied output siblings are never removed.
if [[ -e "${app_path}" ]]; then
  rm -rf "${app_path}"
fi
mv "${staging_app}" "${app_path}"
rm -rf "${staging_root}"
trap - EXIT

echo "Built ${app_path}"
if [[ -n "${developer_id}" ]]; then
  echo "Signature: Developer ID with hardened runtime; notarize the DMG next"
elif [[ ${adhoc_sign} -eq 0 ]]; then
  echo "Signature: unsigned (use --adhoc-sign for local launch testing)"
else
  echo "Signature: ad-hoc only (not suitable for external distribution)"
fi
