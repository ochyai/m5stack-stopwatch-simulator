from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from simulator.backend import NativeSimulatorBackendManager
from simulator.server import MAX_BODY_BYTES, create_server


class FakeBackend:
  def __init__(self, firmware_id: str) -> None:
    self.firmware_id = firmware_id
    self.state = {
      "revision": 1,
      "firmware": {"id": firmware_id},
      "screen": {"mode": "NOW"},
    }
    self.actions: list[str] = []
    self.scenarios: list[dict[str, object]] = []
    self.reset_count = 0
    self.active = 0
    self.overlapped = False
    self.closed = False

  def snapshot(self) -> dict[str, object]:
    self.active += 1
    if self.active > 1:
      self.overlapped = True
    time.sleep(0.002)
    result = dict(self.state)
    self.active -= 1
    return result

  def perform_action(self, action: str) -> dict[str, object]:
    self.actions.append(action)
    self.state["revision"] = int(self.state["revision"]) + 1
    return dict(self.state)

  def configure(self, mapping: dict[str, object]) -> dict[str, object]:
    self.scenarios.append(dict(mapping))
    self.state["revision"] = int(self.state["revision"]) + 1
    return dict(self.state)

  def reset(self) -> dict[str, object]:
    self.reset_count += 1
    self.state["revision"] = 0
    return dict(self.state)

  def close(self) -> None:
    self.closed = True


class HTTPServerTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.static = Path(self.temporary.name) / "static"
    self.static.mkdir()
    (self.static / "index.html").write_text("<!doctype html><title>SOKKON</title>", encoding="utf-8")
    (self.static / "app.js").write_text('"use strict";', encoding="utf-8")
    self.secret = Path(self.temporary.name) / "secret.txt"
    self.secret.write_text("do not serve", encoding="utf-8")
    self.created_backends: list[FakeBackend] = []

    def backend_factory(firmware_id: str) -> FakeBackend:
      backend = FakeBackend(firmware_id)
      self.created_backends.append(backend)
      return backend

    self.manager = NativeSimulatorBackendManager(backend_factory=backend_factory)  # type: ignore[arg-type]
    self.backend = self.created_backends[0]
    self.server = create_server(
      self.manager,
      host="127.0.0.1",
      port=0,
      static_directory=self.static,
    )
    self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
    self.thread.start()
    self.port = self.server.server_address[1]

  def tearDown(self) -> None:
    self.server.shutdown()
    self.server.server_close()
    self.thread.join(timeout=2)
    self.manager.close()
    self.temporary.cleanup()

  def request(
    self,
    method: str,
    path: str,
    *,
    body: bytes | str | None = None,
    headers: dict[str, str] | None = None,
  ) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
    try:
      connection.request(method, path, body=body, headers=headers or {})
      response = connection.getresponse()
      payload = response.read()
      return response.status, {key.lower(): value for key, value in response.getheaders()}, payload
    finally:
      connection.close()

  def json_request(
    self,
    path: str,
    payload: object,
  ) -> tuple[int, dict[str, str], object]:
    status, headers, body = self.request(
      "POST",
      path,
      body=json.dumps(payload).encode("utf-8"),
      headers={"Content-Type": "application/json; charset=utf-8"},
    )
    return status, headers, json.loads(body)

  def test_health_and_state_are_direct_json_without_cache(self) -> None:
    status, headers, body = self.request("GET", "/healthz")
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body), {"status": "ok"})
    self.assertEqual(headers["cache-control"], "no-store")
    self.assertEqual(headers["x-content-type-options"], "nosniff")

    status, headers, body = self.request("GET", "/api/state?fresh=1")
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body), self.backend.state)
    self.assertEqual(headers["content-type"], "application/json; charset=utf-8")

  def test_action_scenario_and_reset_return_snapshots(self) -> None:
    status, _headers, payload = self.json_request("/api/action", {"action": "MARK"})
    self.assertEqual(status, 200)
    self.assertEqual(self.backend.actions, ["mark"])
    self.assertEqual(payload["revision"], 2)

    scenario = {
      "connected": True,
      "outcome": "OK",
      "latency_ms": 400,
      "context": "CODEX",
      "detail": "BUILDING SOKKON",
      "host_mode": "BUILD",
      "battery_percent": 84,
      "charging": False,
      "time_scale": 2,
    }
    status, _headers, payload = self.json_request("/api/scenario", scenario)
    self.assertEqual(status, 200)
    self.assertEqual(self.backend.scenarios, [scenario])
    self.assertEqual(payload["revision"], 3)

    status, _headers, payload = self.json_request("/api/action", {"action": "reset"})
    self.assertEqual(status, 200)
    self.assertEqual(self.backend.reset_count, 0)
    self.assertTrue(self.backend.closed)
    self.assertEqual(len(self.created_backends), 2)
    self.assertEqual(payload["revision"], 1)
    self.assertEqual(payload["firmware"]["id"], "10_sokkon")

  def test_firmware_catalog_and_transactional_switch_return_new_snapshot(self) -> None:
    status, headers, body = self.request("GET", "/api/firmwares")
    self.assertEqual(status, 200)
    self.assertEqual(headers["cache-control"], "no-store")
    self.assertEqual(
      json.loads(body),
      {
        "active": "10_sokkon",
        "firmwares": [
          {"id": "10_sokkon", "label": "SOKKON"},
          {"id": "99_stopwatch", "label": "STOPWATCH"},
        ],
      },
    )

    old_backend = self.backend
    status, _headers, payload = self.json_request(
      "/api/firmware",
      {"firmware": "99_stopwatch"},
    )
    self.assertEqual(status, 200)
    self.assertEqual(payload["firmware"]["id"], "99_stopwatch")
    self.assertTrue(old_backend.closed)
    self.assertEqual(self.manager.firmware_id, "99_stopwatch")
    self.assertEqual(len(self.created_backends), 2)

    status, _headers, body = self.request("GET", "/api/state")
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body)["firmware"]["id"], "99_stopwatch")

    # Re-selecting the active firmware is a transactional Build & Run reload.
    previous_active = self.created_backends[-1]
    status, _headers, payload = self.json_request(
      "/api/firmware",
      {"firmware": "99_stopwatch"},
    )
    self.assertEqual(status, 200)
    self.assertEqual(payload["firmware"]["id"], "99_stopwatch")
    self.assertEqual(len(self.created_backends), 3)
    self.assertTrue(previous_active.closed)

  def test_firmware_catalog_head_has_no_body(self) -> None:
    get_status, get_headers, get_body = self.request("GET", "/api/firmwares")
    head_status, head_headers, head_body = self.request("HEAD", "/api/firmwares")
    self.assertEqual((get_status, head_status), (200, 200))
    self.assertEqual(head_body, b"")
    self.assertEqual(head_headers["content-length"], str(len(get_body)))
    self.assertEqual(head_headers["content-type"], get_headers["content-type"])

  def test_action_and_scenario_validation_return_structured_400(self) -> None:
    cases = (
      ("/api/action", {"action": "launch_missiles"}),
      ("/api/action", {"action": "mark", "extra": True}),
      ("/api/scenario", {"unknown": True}),
      ("/api/scenario", {"connected": 1}),
      ("/api/firmware", {}),
      ("/api/firmware", {"firmware": "99_stopwatch", "extra": True}),
      ("/api/firmware", {"firmware": "../99_stopwatch"}),
      ("/api/firmware", {"firmware": "99_STOPWATCH"}),
      ("/api/firmware", {"firmware": None}),
    )
    for path, payload in cases:
      with self.subTest(path=path, payload=payload):
        status, _headers, response = self.json_request(path, payload)
        self.assertEqual(status, 400)
        self.assertIn("error", response)
        self.assertIn("code", response["error"])

  def test_json_content_type_shape_encoding_and_size_are_strict(self) -> None:
    status, _headers, body = self.request("POST", "/api/action", body=b'{}')
    self.assertEqual(status, 415)
    self.assertIn("error", json.loads(body))

    status, _headers, body = self.request(
      "POST",
      "/api/action",
      body=b"[]",
      headers={"Content-Type": "application/json"},
    )
    self.assertEqual(status, 400)
    self.assertEqual(json.loads(body)["error"]["code"], "invalid_json_type")

    status, _headers, body = self.request(
      "POST",
      "/api/action",
      body=b'{"action":NaN}',
      headers={"Content-Type": "application/json"},
    )
    self.assertEqual(status, 400)
    self.assertEqual(json.loads(body)["error"]["code"], "invalid_json")

    status, _headers, body = self.request(
      "POST",
      "/api/firmware",
      body=b'{"firmware":"10_sokkon","firmware":"99_stopwatch"}',
      headers={"Content-Type": "application/json"},
    )
    self.assertEqual(status, 400)
    self.assertEqual(json.loads(body)["error"]["code"], "invalid_json")
    self.assertEqual(self.manager.firmware_id, "10_sokkon")

    status, _headers, body = self.request(
      "POST",
      "/api/action",
      body=b"x" * (MAX_BODY_BYTES + 1),
      headers={"Content-Type": "application/json"},
    )
    self.assertEqual(status, 413)
    self.assertEqual(json.loads(body)["error"]["code"], "body_too_large")

  def test_static_files_have_safe_mapping_mime_and_security_headers(self) -> None:
    status, headers, body = self.request("GET", "/")
    self.assertEqual(status, 200)
    self.assertIn(b"SOKKON", body)
    self.assertEqual(headers["content-type"], "text/html; charset=utf-8")
    self.assertEqual(headers["x-frame-options"], "DENY")
    self.assertIn("default-src 'self'", headers["content-security-policy"])

    status, headers, body = self.request("GET", "/static/app.js?v=1")
    self.assertEqual(status, 200)
    self.assertEqual(body, b'"use strict";')
    self.assertIn("javascript", headers["content-type"])
    self.assertEqual(headers["cache-control"], "no-cache")

  def test_path_traversal_and_symlink_escape_are_not_served(self) -> None:
    (self.static / "escape.txt").symlink_to(self.secret)
    for path in (
      "/static/%2e%2e/secret.txt",
      "/static/../secret.txt",
      "/static/escape.txt",
      "/secret.txt",
    ):
      with self.subTest(path=path):
        status, _headers, body = self.request("GET", path)
        self.assertEqual(status, 404)
        self.assertNotIn(b"do not serve", body)

  def test_methods_are_restricted_and_cors_is_not_enabled(self) -> None:
    status, headers, body = self.request("OPTIONS", "/api/action")
    self.assertEqual(status, 405)
    self.assertNotIn("access-control-allow-origin", headers)
    self.assertIn("error", json.loads(body))

    status, headers, body = self.request("POST", "/api/state", body=b"")
    self.assertEqual(status, 405)
    self.assertEqual(headers["allow"], "GET, HEAD")
    self.assertIn("error", json.loads(body))

    status, headers, body = self.request("GET", "/api/firmware")
    self.assertEqual(status, 405)
    self.assertEqual(headers["allow"], "POST")
    self.assertIn("error", json.loads(body))

    status, headers, body = self.request(
      "POST",
      "/api/firmwares",
      body=b"{}",
      headers={"Content-Type": "application/json"},
    )
    self.assertEqual(status, 405)
    self.assertEqual(headers["allow"], "GET, HEAD")
    self.assertIn("error", json.loads(body))

    status, headers, body = self.request("OPTIONS", "/api/firmware")
    self.assertEqual(status, 405)
    self.assertEqual(headers["allow"], "POST")
    self.assertNotIn("access-control-allow-origin", headers)
    self.assertIn("error", json.loads(body))

  def test_loopback_host_and_origin_reject_dns_rebinding_requests(self) -> None:
    hostile_requests = (
      {"Host": f"attacker.example:{self.port}"},
      {"Host": "127.0.0.1:1"},
      {
        "Host": f"127.0.0.1:{self.port}",
        "Origin": "https://attacker.example",
      },
      {
        "Host": f"127.0.0.1:{self.port}",
        "Origin": "null",
      },
    )
    for headers in hostile_requests:
      with self.subTest(headers=headers):
        status, _response_headers, body = self.request(
          "GET",
          "/api/state",
          headers=headers,
        )
        self.assertEqual(status, 403)
        self.assertIn(
          json.loads(body)["error"]["code"],
          ("untrusted_host", "cross_origin_request"),
        )

    status, _headers, body = self.request(
      "POST",
      "/api/action",
      body=b'{"action":"mark"}',
      headers={
        "Content-Type": "application/json",
        "Host": f"localhost:{self.port}",
        "Origin": "http://127.0.0.1:4173",
      },
    )
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body)["revision"], 2)
    self.assertEqual(self.backend.actions, ["mark"])

  def test_non_loopback_binding_requires_origin_to_match_request_host(self) -> None:
    self.server.loopback_binding = False
    matching = {
      "Host": f"simulator.example:{self.port}",
      "Origin": f"http://simulator.example:{self.port}",
    }
    status, _headers, body = self.request("GET", "/healthz", headers=matching)
    self.assertEqual(status, 200)
    self.assertEqual(json.loads(body), {"status": "ok"})

    status, _headers, body = self.request(
      "GET",
      "/healthz",
      headers={**matching, "Origin": f"http://other.example:{self.port}"},
    )
    self.assertEqual(status, 403)
    self.assertEqual(json.loads(body)["error"]["code"], "cross_origin_request")

  def test_server_lock_serializes_backend_access(self) -> None:
    with ThreadPoolExecutor(max_workers=12) as executor:
      responses = list(executor.map(lambda _index: self.request("GET", "/api/state"), range(30)))
    self.assertTrue(all(status == 200 for status, _headers, _body in responses))
    self.assertFalse(self.backend.overlapped)

  def test_firmware_switch_is_serialized_with_state_requests(self) -> None:
    old_backend = self.backend

    def request_or_switch(index: int) -> tuple[int, str]:
      if index == 8:
        status, _headers, payload = self.json_request(
          "/api/firmware",
          {"firmware": "99_stopwatch"},
        )
        assert isinstance(payload, dict)
        firmware = payload["firmware"]
        assert isinstance(firmware, dict)
        return status, str(firmware["id"])
      status, _headers, body = self.request("GET", "/api/state")
      payload = json.loads(body)
      return status, str(payload["firmware"]["id"])

    with ThreadPoolExecutor(max_workers=12) as executor:
      responses = list(executor.map(request_or_switch, range(32)))

    self.assertTrue(all(status == 200 for status, _firmware_id in responses))
    self.assertTrue(
      all(
        firmware_id in ("10_sokkon", "99_stopwatch")
        for _status, firmware_id in responses
      )
    )
    self.assertTrue(old_backend.closed)
    self.assertTrue(all(not backend.overlapped for backend in self.created_backends))
    self.assertEqual(self.manager.firmware_id, "99_stopwatch")


if __name__ == "__main__":
  unittest.main()
