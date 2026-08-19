from __future__ import annotations

import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import threading
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class _HealthyHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        if self.path == "/healthz":
            body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, _format: str, *args: object) -> None:
        del args


class _UnavailableHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
        body = b'{"error":"not this service"}'
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *args: object) -> None:
        del args


class WorkbenchLauncherTest(unittest.TestCase):
    def fake_repository(self) -> tuple[Path, Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        launcher = root / "scripts" / "run-workbench.sh"
        launcher.parent.mkdir(parents=True)
        shutil.copy2(REPOSITORY_ROOT / "scripts" / "run-workbench.sh", launcher)
        (root / "simulator" / "workbench" / "node_modules").mkdir(parents=True)
        (root / "simulator" / "__init__.py").write_text("", encoding="utf-8")
        (root / "simulator" / "__main__.py").write_text(
            """
import os
from pathlib import Path
import signal
import time

child = os.fork()
if child == 0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    marker = Path(os.environ["FAKE_COMPILER_PID_FILE"])
    with marker.open("w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
        handle.flush()
        os.fsync(handle.fileno())
    while True:
        time.sleep(1)

while True:
    time.sleep(1)
""".lstrip(),
            encoding="utf-8",
        )
        marker = root / "compiler.pid"
        return root, launcher, marker

    @staticmethod
    def free_port() -> int:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])
        finally:
            listener.close()

    @staticmethod
    def wait_for_file(path: Path, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file() and path.read_text(encoding="utf-8").strip():
                return
            time.sleep(0.02)
        raise AssertionError(f"timed out waiting for {path}")

    @staticmethod
    def process_is_running(pid: int) -> bool:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="],
            capture_output=True,
            text=True,
            check=False,
        )
        status = result.stdout.strip()
        return result.returncode == 0 and bool(status) and not status.startswith("Z")

    def assert_process_stops(self, pid: int, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.process_is_running(pid):
                return
            time.sleep(0.05)
        self.fail(f"descendant process {pid} is still running")

    @staticmethod
    def force_kill(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def test_allows_a_bounded_two_minute_clean_build_window(self) -> None:
        launcher = (REPOSITORY_ROOT / "scripts" / "run-workbench.sh").read_text()
        self.assertIn('BACKEND_START_TIMEOUT_SECONDS:-120', launcher)
        self.assertIn("backend_start_timeout_seconds > 300", launcher)

    def test_refuses_an_existing_healthy_backend_instead_of_using_it(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthyHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        environment = os.environ.copy()
        environment["BACKEND_PORT"] = str(server.server_port)
        result = subprocess.run(
            [str(REPOSITORY_ROOT / "scripts" / "run-workbench.sh")],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn(
            f"backend port {server.server_port} is already in use", result.stderr
        )

    def test_refuses_any_tcp_port_owner_before_starting_the_backend(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _UnavailableHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        _root, launcher, marker = self.fake_repository()

        environment = os.environ.copy()
        environment["BACKEND_PORT"] = str(server.server_port)
        environment["BACKEND_START_TIMEOUT_SECONDS"] = "1"
        environment["FAKE_COMPILER_PID_FILE"] = str(marker)
        started = time.monotonic()
        result = subprocess.run(
            [str(launcher)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertLess(time.monotonic() - started, 2)
        self.assertIn(
            f"backend port {server.server_port} is already in use", result.stderr
        )
        self.assertFalse(marker.exists(), "backend started before port rejection")

    def test_term_reaps_the_private_backend_process_group(self) -> None:
        _root, launcher, marker = self.fake_repository()
        environment = os.environ.copy()
        environment["BACKEND_PORT"] = str(self.free_port())
        environment["FAKE_COMPILER_PID_FILE"] = str(marker)
        process = subprocess.Popen(
            [str(launcher)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.wait_for_file(marker)
        compiler_pid = int(marker.read_text(encoding="utf-8"))
        self.addCleanup(self.force_kill, compiler_pid)

        process.terminate()
        stdout, stderr = process.communicate(timeout=6)

        self.assertEqual(process.returncode, 143, stdout + stderr)
        self.assert_process_stops(compiler_pid)

    def test_startup_timeout_reaps_the_private_backend_process_group(self) -> None:
        _root, launcher, marker = self.fake_repository()
        environment = os.environ.copy()
        environment["BACKEND_PORT"] = str(self.free_port())
        environment["BACKEND_START_TIMEOUT_SECONDS"] = "1"
        environment["FAKE_COMPILER_PID_FILE"] = str(marker)
        process = subprocess.Popen(
            [str(launcher)],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.wait_for_file(marker)
        compiler_pid = int(marker.read_text(encoding="utf-8"))
        self.addCleanup(self.force_kill, compiler_pid)

        stdout, stderr = process.communicate(timeout=8)

        self.assertEqual(process.returncode, 1, stdout + stderr)
        self.assertIn("simulator backend did not become healthy", stderr)
        self.assert_process_stops(compiler_pid)


if __name__ == "__main__":
    unittest.main()
