#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "${script_dir}/.." && pwd)"
workbench_dir="${repository_root}/simulator/workbench"
backend_port="${BACKEND_PORT:-8765}"
workbench_port="${WORKBENCH_PORT:-4173}"
firmware_id="${FIRMWARE:-99_stopwatch}"
backend_start_timeout_seconds="${BACKEND_START_TIMEOUT_SECONDS:-120}"

case "${firmware_id}" in
  10_sokkon|99_stopwatch) ;;
  *)
    echo "unsupported workbench firmware: ${firmware_id}" >&2
    exit 2
    ;;
esac

if [[ ! "${backend_start_timeout_seconds}" =~ ^[1-9][0-9]*$ ]] \
  || (( backend_start_timeout_seconds > 300 )); then
  echo "BACKEND_START_TIMEOUT_SECONDS must be an integer from 1 to 300" >&2
  exit 2
fi

# Probe the TCP listener itself instead of trusting a particular /healthz
# response. An unrelated service can own the port while returning 404/503;
# discovering that only after a clean native build wastes the full startup
# window. SO_REUSEADDR mirrors ThreadingHTTPServer's bind behavior and avoids
# treating a harmless TIME_WAIT socket as a live listener.
backend_port_status=0
python3 -c '
import errno
import socket
import sys

raw_port = sys.argv[1]
if not raw_port.isascii() or not raw_port.isdecimal():
    raise SystemExit(2)
port = int(raw_port, 10)
if not 1 <= port <= 65535:
    raise SystemExit(2)

probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    probe.bind(("127.0.0.1", port))
except OSError as error:
    if error.errno == errno.EADDRINUSE:
        raise SystemExit(1)
    print(f"could not probe backend port {port}: {error}", file=sys.stderr)
    raise SystemExit(3)
finally:
    probe.close()
' "${backend_port}" || backend_port_status="$?"

case "${backend_port_status}" in
  0) ;;
  1)
    echo "simulator backend port ${backend_port} is already in use" >&2
    exit 1
    ;;
  2)
    echo "BACKEND_PORT must be an integer from 1 to 65535" >&2
    exit 2
    ;;
  *)
    echo "simulator backend port ${backend_port} could not be checked" >&2
    exit 1
    ;;
esac

if [[ ! -d "${workbench_dir}/node_modules" ]]; then
  echo "workbench dependencies are missing; run: make workbench-install" >&2
  exit 2
fi

backend_pid=""
backend_process_group=""

backend_group_is_alive() {
  [[ -n "${backend_process_group}" ]] \
    && kill -0 -- "-${backend_process_group}" 2>/dev/null
}

cleanup() {
  local exit_status="$?"
  local attempt

  # Do not let a second signal interrupt child reaping halfway through.
  trap - EXIT
  trap '' INT TERM

  if [[ -n "${backend_pid}" ]]; then
    if backend_group_is_alive; then
      kill -TERM -- "-${backend_process_group}" 2>/dev/null || true
    elif kill -0 "${backend_pid}" 2>/dev/null; then
      # Covers the very small interval before the child has called setsid().
      kill -TERM "${backend_pid}" 2>/dev/null || true
    fi

    # Give Python/build tools a bounded cooperative exit, then kill the whole
    # private group. This also catches a compiler whose parent already exited.
    for attempt in {1..20}; do
      if ! backend_group_is_alive && ! kill -0 "${backend_pid}" 2>/dev/null; then
        break
      fi
      sleep 0.05
    done
    if backend_group_is_alive; then
      kill -KILL -- "-${backend_process_group}" 2>/dev/null || true
    elif kill -0 "${backend_pid}" 2>/dev/null; then
      kill -KILL "${backend_pid}" 2>/dev/null || true
    fi
    wait "${backend_pid}" 2>/dev/null || true
  fi

  exit "${exit_status}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cd "${repository_root}"
# Python's setsid() is available on both macOS and Linux. The wrapper execs in
# place, so $! remains the backend PID and also becomes its private process
# group ID. build-simulator.sh and its compiler inherit that group.
python3 -c '
import os
import sys

os.setsid()
os.execv(sys.executable, [sys.executable, "-m", "simulator", *sys.argv[1:]])
' \
  --firmware "${firmware_id}" \
  --host 127.0.0.1 \
  --port "${backend_port}" \
  --no-open &
backend_pid="$!"
backend_process_group="${backend_pid}"

# A clean checkout compiles the selected native runner before binding. Give
# that bounded first build enough time while still failing as soon as the
# child exits or another process was found during the preflight above.
backend_start_deadline="$(( $(date +%s) + backend_start_timeout_seconds ))"
while (( $(date +%s) <= backend_start_deadline )); do
  if ! kill -0 "${backend_pid}" 2>/dev/null; then
    wait "${backend_pid}"
  fi
  if curl --fail --silent --show-error --connect-timeout 0.2 --max-time 0.5 \
    "http://127.0.0.1:${backend_port}/healthz" >/dev/null; then
    if ! kill -0 "${backend_pid}" 2>/dev/null; then
      wait "${backend_pid}"
    fi
    break
  fi
  sleep 0.1
done

if ! curl --fail --silent --show-error --connect-timeout 0.2 --max-time 0.5 \
  "http://127.0.0.1:${backend_port}/healthz" >/dev/null; then
  echo "simulator backend did not become healthy" >&2
  exit 1
fi

if ! kill -0 "${backend_pid}" 2>/dev/null; then
  wait "${backend_pid}"
fi

cd "${workbench_dir}"
npm run dev -- \
  --host 127.0.0.1 \
  --port "${workbench_port}" \
  --strictPort
