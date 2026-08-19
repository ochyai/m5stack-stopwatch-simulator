from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from simulator.server import MAX_BODY_BYTES, create_server


class FakeBackend:
  def __init__(self) -> None:
    self.state = {"revision": 1, "screen": {"mode": "NOW"}}
    self.actions: list[str] = []
    self.scenarios: list[dict[str, object]] = []
    self.reset_count = 0
    self.active = 0
    self.overlapped = False

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


class HTTPServerTest(unittest.TestCase):
  def setUp(self) -> None:
    self.temporary = tempfile.TemporaryDirectory()
    self.static = Path(self.temporary.name) / "static"
    self.static.mkdir()
    (self.static / "index.html").write_text("<!doctype html><title>SOKKON</title>", encoding="utf-8")
    (self.static / "app.js").write_text('"use strict";', encoding="utf-8")
    self.secret = Path(self.temporary.name) / "secret.txt"
    self.secret.write_text("do not serve", encoding="utf-8")
    self.backend = FakeBackend()
    self.server = create_server(
      self.backend,
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
    self.assertEqual(self.backend.reset_count, 1)
    self.assertEqual(payload["revision"], 0)

  def test_action_and_scenario_validation_return_structured_400(self) -> None:
    cases = (
      ("/api/action", {"action": "launch_missiles"}),
      ("/api/action", {"action": "mark", "extra": True}),
      ("/api/scenario", {"unknown": True}),
      ("/api/scenario", {"connected": 1}),
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

  def test_server_lock_serializes_backend_access(self) -> None:
    with ThreadPoolExecutor(max_workers=12) as executor:
      responses = list(executor.map(lambda _index: self.request("GET", "/api/state"), range(30)))
    self.assertTrue(all(status == 200 for status, _headers, _body in responses))
    self.assertFalse(self.backend.overlapped)


if __name__ == "__main__":
  unittest.main()
