#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
compiler="${CXX:-c++}"
output_dir="${repository_root}/.simulator"
output_path="${output_dir}/sokkon-native"
temporary_path="${output_path}.tmp"

# These are deliberately the production sources, not simulator-side copies.
production_main="firmware/apps/10_sokkon/main.cpp"
production_board="firmware/shared/board.cpp"

mkdir -p "${output_dir}"

"${compiler}" \
  -std=c++17 \
  -O2 \
  -Wall \
  -Wextra \
  -Wpedantic \
  -I"${repository_root}/simulator/native/include" \
  -I"${repository_root}/firmware/shared" \
  -I"${repository_root}" \
  "-DSOKKON_PRODUCTION_MAIN=\"${production_main}\"" \
  "${repository_root}/simulator/native/runner.cpp" \
  "${repository_root}/${production_board}" \
  -o "${temporary_path}"

mv "${temporary_path}" "${output_path}"
echo "Built ${output_path} from ${production_main} and ${production_board}"
