#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
compiler="${CXX:-c++}"
output_dir="${repository_root}/.simulator"
firmware_id="10_sokkon"

if [[ $# -gt 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--firmware" ]]; then
    echo "usage: $0 [--firmware 10_sokkon|99_stopwatch]" >&2
    exit 2
  fi
  firmware_id="$2"
fi

# This fixed registry is also the path-traversal boundary. HTTP/CLI callers
# choose an identifier; they can never supply a source, runner, output path,
# compiler option, or arbitrary environment expansion.
case "${firmware_id}" in
  10_sokkon)
    production_main="firmware/apps/10_sokkon/main.cpp"
    runner="simulator/native/runner.cpp"
    output_path="${output_dir}/sokkon-native"
    ;;
  99_stopwatch)
    production_main="firmware/apps/99_stopwatch/main.cpp"
    runner="simulator/native/stopwatch_runner.cpp"
    output_path="${output_dir}/stopwatch-native"
    ;;
  *)
    echo "unsupported simulator firmware: ${firmware_id}" >&2
    exit 2
    ;;
esac

# These are deliberately the production sources, not simulator-side copies.
production_board="firmware/shared/board.cpp"

mkdir -p "${output_dir}"
temporary_path="$(mktemp "${output_path}.tmp.XXXXXX")"
runner_object="$(mktemp "${output_path}.runner.o.tmp.XXXXXX")"
board_object="$(mktemp "${output_path}.board.o.tmp.XXXXXX")"
runner_dependency_path="${output_path}.runner.d"
board_dependency_path="${output_path}.board.d"
runner_dependency_temporary_path="$(mktemp "${runner_dependency_path}.tmp.XXXXXX")"
board_dependency_temporary_path="$(mktemp "${board_dependency_path}.tmp.XXXXXX")"
trap 'rm -f "${temporary_path}" "${runner_object}" "${board_object}" "${runner_dependency_temporary_path}" "${board_dependency_temporary_path}"' EXIT

"${compiler}" \
  -std=c++17 \
  -O2 \
  -Wall \
  -Wextra \
  -Wpedantic \
  -MMD \
  -MF "${runner_dependency_temporary_path}" \
  -MT "${output_path}" \
  -I"${repository_root}/simulator/native/include" \
  -I"${repository_root}/firmware/shared" \
  -I"${repository_root}" \
  "-DSIMULATOR_PRODUCTION_MAIN=\"${production_main}\"" \
  "${repository_root}/${runner}" \
  -c \
  -o "${runner_object}"

"${compiler}" \
  -std=c++17 \
  -O2 \
  -Wall \
  -Wextra \
  -Wpedantic \
  -MMD \
  -MF "${board_dependency_temporary_path}" \
  -MT "${output_path}" \
  -I"${repository_root}/simulator/native/include" \
  -I"${repository_root}/firmware/shared" \
  -I"${repository_root}" \
  "${repository_root}/${production_board}" \
  -c \
  -o "${board_object}"

"${compiler}" "${runner_object}" "${board_object}" -o "${temporary_path}"

# Publish manifests before the binary. An interrupted build therefore leaves
# either the previous coherent artifact or dependency files newer than it,
# which forces the backend to rebuild on its next start.
mv "${runner_dependency_temporary_path}" "${runner_dependency_path}"
mv "${board_dependency_temporary_path}" "${board_dependency_path}"
mv "${temporary_path}" "${output_path}"
rm -f "${runner_object}" "${board_object}"
trap - EXIT
echo "Built ${output_path} (${firmware_id}) from ${production_main} and ${production_board}"
