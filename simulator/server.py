"""Loopback-only-by-default HTTP server for the SOKKON simulator UI."""

from __future__ import annotations

from collections.abc import Callable
import ipaddress
import json
import logging
import mimetypes
from pathlib import Path, PurePosixPath
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any
from urllib.parse import unquote_to_bytes, urlsplit

from .backend import (
  BackendError,
  BackendInputError,
  firmware_spec,
  normalize_action,
  normalize_configuration,
)


LOGGER = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8_765
MAX_BODY_BYTES = 64 * 1024
DEFAULT_STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
  """Build a JSON object while refusing ambiguous duplicate field names."""
  result: dict[str, Any] = {}
  for key, value in pairs:
    if key in result:
      raise ValueError(f"duplicate JSON field: {key}")
    result[key] = value
  return result


def _canonical_hostname(hostname: str) -> str:
  normalized = hostname.rstrip(".").lower()
  try:
    return ipaddress.ip_address(normalized).compressed
  except ValueError:
    return normalized


def _hostname_is_loopback(hostname: str) -> bool:
  normalized = _canonical_hostname(hostname)
  if normalized == "localhost":
    return True
  try:
    address = ipaddress.ip_address(normalized)
  except ValueError:
    return False
  if address.is_loopback:
    return True
  mapped = getattr(address, "ipv4_mapped", None)
  return mapped is not None and mapped.is_loopback


def _parse_authority(value: str) -> tuple[str, int | None]:
  if not value or any(character in value for character in "\0\r\n\t/?#@"):
    raise ValueError("invalid authority")
  parsed = urlsplit(f"//{value}")
  if (
    parsed.scheme
    or parsed.username is not None
    or parsed.password is not None
    or parsed.path
    or parsed.query
    or parsed.fragment
    or parsed.hostname is None
  ):
    raise ValueError("invalid authority")
  port = parsed.port  # Access validates malformed and out-of-range ports.
  return _canonical_hostname(parsed.hostname), port


def _parse_origin(value: str) -> tuple[str, str, int]:
  parsed = urlsplit(value)
  if (
    parsed.scheme not in ("http", "https")
    or parsed.username is not None
    or parsed.password is not None
    or parsed.hostname is None
    or parsed.path
    or parsed.query
    or parsed.fragment
  ):
    raise ValueError("invalid origin")
  port = parsed.port
  if port is None:
    port = 443 if parsed.scheme == "https" else 80
  return parsed.scheme, _canonical_hostname(parsed.hostname), port


class RequestError(Exception):
  """An HTTP request error safe to return to the local client."""

  def __init__(
    self,
    status: HTTPStatus,
    code: str,
    message: str,
    *,
    close_connection: bool = False,
  ) -> None:
    super().__init__(message)
    self.status = status
    self.code = code
    self.message = message
    self.close_connection = close_connection


class SimulatorHTTPServer(ThreadingHTTPServer):
  """HTTP server carrying one backend shared safely by request threads."""

  daemon_threads = True
  block_on_close = False
  allow_reuse_address = True

  def __init__(
    self,
    server_address: tuple[str, int],
    backend: Any,
    static_directory: Path,
    recorder: Any = None,
  ) -> None:
    self.backend = backend
    self.recorder = recorder
    self.backend_lock = threading.RLock()
    self.static_directory = static_directory.resolve()
    super().__init__(server_address, SimulatorRequestHandler)
    self.loopback_binding = _hostname_is_loopback(str(self.server_address[0]))


class IPv6SimulatorHTTPServer(SimulatorHTTPServer):
  address_family = socket.AF_INET6


class SimulatorRequestHandler(BaseHTTPRequestHandler):
  """Serve the bundled UI and a deliberately small JSON API."""

  server: SimulatorHTTPServer
  server_version = "SokkonSimulator/1"
  sys_version = ""

  def setup(self) -> None:
    super().setup()
    self.connection.settimeout(10.0)

  def version_string(self) -> str:
    return self.server_version

  def log_message(self, format: str, *args: object) -> None:
    """Keep the 10 Hz state poll quiet unless debug logging is enabled."""
    LOGGER.debug("%s - %s", self.client_address[0], format % args)

  def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
    self._handle_get(head_only=False)

  def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
    self._handle_get(head_only=True)

  def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
    try:
      path = self._request_path()
      if path == "/api/action":
        payload = self._read_json_object()
        fields = set(payload)
        if fields == {"action", "x", "y"}:
          action = normalize_action(payload["action"])
          if action != "touch":
            raise RequestError(
              HTTPStatus.BAD_REQUEST,
              "invalid_action_request",
              "only a touch action carries a coordinate",
            )
          x, y = payload["x"], payload["y"]
          body = self._backend_json(lambda: self.server.backend.touch(x, y))
          self._record(lambda recorder: recorder.record_touch(x, y))
          self._send_json_bytes(HTTPStatus.OK, body)
          return
        if fields != {"action"}:
          raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "invalid_action_request",
            "action request must contain exactly one 'action' field",
          )
        action = normalize_action(payload["action"])
        if action == "touch":
          raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "invalid_action_request",
            "a touch action requires 'x' and 'y'",
          )
        if action == "reset":
          body = self._backend_json(lambda: self.server.backend.reset())
        else:
          body = self._backend_json(
            lambda: self.server.backend.perform_action(action)
          )
        # Record only what the backend accepted, so a recording always replays.
        self._record(lambda recorder: recorder.record_action(action))
        self._send_json_bytes(HTTPStatus.OK, body)
        return
      if path == "/api/scenario":
        payload = self._read_json_object()
        # Validate here as well as in the production backend so injected test or
        # alternate backends cannot accidentally widen the public API.
        normalize_configuration(payload)
        body = self._backend_json(lambda: self.server.backend.configure(payload))
        self._record(lambda recorder: recorder.record_configuration(payload))
        self._send_json_bytes(HTTPStatus.OK, body)
        return
      if path == "/api/firmware":
        payload = self._read_json_object()
        if set(payload) != {"firmware"}:
          raise RequestError(
            HTTPStatus.BAD_REQUEST,
            "invalid_firmware_request",
            "firmware request must contain exactly one 'firmware' field",
          )
        target_id = firmware_spec(payload["firmware"]).firmware_id
        body = self._backend_json(
          lambda: self.server.backend.switch_firmware(target_id)
        )
        self._send_json_bytes(HTTPStatus.OK, body)
        return
      if path in ("/healthz", "/api/state", "/api/firmwares"):
        self._send_method_not_allowed("GET, HEAD")
        return
      if path.startswith("/api/"):
        self._send_error_json(HTTPStatus.NOT_FOUND, "not_found", "API endpoint not found")
        return
      self.close_connection = True
      self._send_method_not_allowed("GET, HEAD")
    except RequestError as error:
      if error.close_connection:
        self.close_connection = True
      self._send_error_json(error.status, error.code, error.message)
    except BackendInputError as error:
      self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_input", str(error))
    except (ValueError, KeyError) as error:
      message = error.args[0] if isinstance(error, KeyError) and error.args else str(error)
      self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid_input", str(message))
    except BackendError as error:
      LOGGER.warning("native simulator request failed: %s", error)
      self._send_error_json(
        HTTPStatus.BAD_GATEWAY,
        "backend_failure",
        "native simulator did not produce a valid response",
      )
    except Exception:
      LOGGER.exception("unexpected simulator request failure")
      self._send_error_json(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "internal_error",
        "simulator request failed",
      )

  def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
    # Deliberately no CORS opt-in.  application/json POSTs from a foreign page
    # must fail their browser preflight before reaching local simulator state.
    try:
      path = self._request_path()
      if path in ("/api/action", "/api/scenario", "/api/firmware"):
        allow = "POST"
      elif path in ("/healthz", "/api/state", "/api/firmwares"):
        allow = "GET, HEAD"
      else:
        allow = "GET, HEAD, POST"
      self._send_method_not_allowed(allow)
    except RequestError as error:
      if error.close_connection:
        self.close_connection = True
      self._send_error_json(error.status, error.code, error.message)

  def send_error(
    self,
    code: int,
    message: str | None = None,
    explain: str | None = None,
  ) -> None:
    """Keep parser and unsupported-method failures out of HTML responses."""
    try:
      status = HTTPStatus(code)
    except ValueError:
      status = HTTPStatus.INTERNAL_SERVER_ERROR
    self._send_error_json(
      status,
      "http_error",
      message or explain or status.phrase,
    )

  def _handle_get(self, *, head_only: bool) -> None:
    try:
      path = self._request_path()
      if path == "/healthz":
        self._send_json(HTTPStatus.OK, {"status": "ok"}, head_only=head_only)
        return
      if path == "/api/state":
        body = self._backend_json(lambda: self.server.backend.snapshot())
        self._send_json_bytes(HTTPStatus.OK, body, head_only=head_only)
        return
      if path == "/api/firmwares":
        body = self._backend_json(lambda: self.server.backend.firmwares())
        self._send_json_bytes(HTTPStatus.OK, body, head_only=head_only)
        return
      if path in ("/api/action", "/api/scenario", "/api/firmware"):
        self._send_method_not_allowed("POST", head_only=head_only)
        return
      if path.startswith("/api/"):
        self._send_error_json(
          HTTPStatus.NOT_FOUND,
          "not_found",
          "API endpoint not found",
          head_only=head_only,
        )
        return
      self._serve_static(path, head_only=head_only)
    except RequestError as error:
      if error.close_connection:
        self.close_connection = True
      self._send_error_json(
        error.status,
        error.code,
        error.message,
        head_only=head_only,
      )
    except BackendError as error:
      LOGGER.warning("native simulator request failed: %s", error)
      self._send_error_json(
        HTTPStatus.BAD_GATEWAY,
        "backend_failure",
        "native simulator did not produce a valid response",
        head_only=head_only,
      )
    except Exception:
      LOGGER.exception("unexpected simulator request failure")
      self._send_error_json(
        HTTPStatus.INTERNAL_SERVER_ERROR,
        "internal_error",
        "simulator request failed",
        head_only=head_only,
      )

  def _request_path(self) -> str:
    self._validate_request_authority()
    if not self.path.startswith("/") or self.path.startswith("//"):
      raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_path", "invalid request path")
    parsed = urlsplit(self.path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
      raise RequestError(HTTPStatus.BAD_REQUEST, "invalid_path", "invalid request path")
    try:
      return unquote_to_bytes(parsed.path).decode("utf-8")
    except UnicodeDecodeError as error:
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "invalid_path",
        "request path must be valid UTF-8",
      ) from error

  def _validate_request_authority(self) -> None:
    host_values = self.headers.get_all("Host", [])
    if len(host_values) != 1:
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "invalid_host",
        "one valid Host header is required",
        close_connection=True,
      )
    try:
      host, host_port = _parse_authority(host_values[0])
    except ValueError as error:
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "invalid_host",
        "one valid Host header is required",
        close_connection=True,
      ) from error

    if self.server.loopback_binding:
      expected_port = int(self.server.server_address[1])
      effective_host_port = 80 if host_port is None else host_port
      if not _hostname_is_loopback(host) or effective_host_port != expected_port:
        raise RequestError(
          HTTPStatus.FORBIDDEN,
          "untrusted_host",
          "Host must identify this loopback simulator",
          close_connection=True,
        )

    origin_values = self.headers.get_all("Origin", [])
    if not origin_values:
      return
    if len(origin_values) != 1:
      raise RequestError(
        HTTPStatus.FORBIDDEN,
        "cross_origin_request",
        "request origin is not trusted",
        close_connection=True,
      )
    try:
      origin_scheme, origin_host, origin_port = _parse_origin(origin_values[0])
    except ValueError as error:
      raise RequestError(
        HTTPStatus.FORBIDDEN,
        "cross_origin_request",
        "request origin is not trusted",
        close_connection=True,
      ) from error

    if self.server.loopback_binding:
      # The Workbench intentionally proxies from another loopback port. Treat
      # loopback origins as one local development trust boundary while refusing
      # DNS-rebinding names and every public/private-network web origin.
      trusted_origin = _hostname_is_loopback(origin_host)
    else:
      effective_host_port = 80 if host_port is None else host_port
      trusted_origin = (
        origin_scheme == "http"
        and origin_host == host
        and origin_port == effective_host_port
      )
    if not trusted_origin:
      raise RequestError(
        HTTPStatus.FORBIDDEN,
        "cross_origin_request",
        "request origin is not trusted",
        close_connection=True,
      )

  def _read_json_object(self) -> dict[str, Any]:
    transfer_encodings = self.headers.get_all("Transfer-Encoding", [])
    if transfer_encodings:
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "unsupported_transfer_encoding",
        "Transfer-Encoding is not supported",
        close_connection=True,
      )
    content_encodings = self.headers.get_all("Content-Encoding", [])
    if content_encodings:
      raise RequestError(
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        "unsupported_content_encoding",
        "Content-Encoding is not supported",
        close_connection=True,
      )

    content_types = self.headers.get_all("Content-Type", [])
    if len(content_types) != 1 or self.headers.get_content_type() != "application/json":
      raise RequestError(
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        "invalid_content_type",
        "Content-Type must be application/json",
        close_connection=True,
      )
    parameters = self.headers.get_params(header="content-type", failobj=[])[1:]
    if any(name.lower() != "charset" for name, _value in parameters):
      raise RequestError(
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        "invalid_content_type",
        "only the UTF-8 charset parameter is supported",
        close_connection=True,
      )
    charset = self.headers.get_content_charset()
    if charset is not None and charset.lower() != "utf-8":
      raise RequestError(
        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
        "invalid_charset",
        "JSON request charset must be UTF-8",
        close_connection=True,
      )

    lengths = self.headers.get_all("Content-Length", [])
    if len(lengths) != 1:
      raise RequestError(
        HTTPStatus.LENGTH_REQUIRED,
        "content_length_required",
        "one Content-Length header is required",
        close_connection=True,
      )
    raw_length = lengths[0]
    if not raw_length.isascii() or not raw_length.isdecimal():
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "invalid_content_length",
        "Content-Length must be an unsigned decimal integer",
        close_connection=True,
      )
    length = int(raw_length)
    if length > MAX_BODY_BYTES:
      raise RequestError(
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        "body_too_large",
        f"JSON body cannot exceed {MAX_BODY_BYTES} bytes",
        close_connection=True,
      )
    try:
      body = self.rfile.read(length)
    except (OSError, TimeoutError) as error:
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "incomplete_body",
        "request body could not be read",
        close_connection=True,
      ) from error
    if len(body) != length:
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "incomplete_body",
        "request body ended before Content-Length",
        close_connection=True,
      )
    try:
      text = body.decode("utf-8")
      payload = json.loads(
        text,
        object_pairs_hook=_reject_duplicate_json_fields,
        parse_constant=lambda value: (_ for _ in ()).throw(
          ValueError(f"invalid JSON constant {value}")
        ),
      )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "invalid_json",
        f"body must be one valid UTF-8 JSON document: {error}",
      ) from error
    if not isinstance(payload, dict):
      raise RequestError(
        HTTPStatus.BAD_REQUEST,
        "invalid_json_type",
        "JSON body must be an object",
      )
    return payload

  def _record(self, callback: Callable[[Any], None]) -> None:
    """Append to the session recording, never failing the request for it."""
    recorder = getattr(self.server, "recorder", None)
    if recorder is None:
      return
    try:
      with self.server.backend_lock:
        callback(recorder)
    except OSError as error:
      LOGGER.warning("session recording failed: %s", error)

  def _backend_json(self, callback: Callable[[], object]) -> bytes:
    with self.server.backend_lock:
      snapshot = callback()
      return self._encode_json(snapshot)

  def _serve_static(self, request_path: str, *, head_only: bool) -> None:
    if request_path in ("/", "/index.html"):
      relative = PurePosixPath("index.html")
    elif request_path.startswith("/static/"):
      suffix = request_path.removeprefix("/static/")
      if not suffix:
        raise RequestError(HTTPStatus.NOT_FOUND, "not_found", "static file not found")
      relative = PurePosixPath(suffix)
    else:
      raise RequestError(HTTPStatus.NOT_FOUND, "not_found", "resource not found")

    if (
      "\\" in request_path
      or "\0" in request_path
      or relative.is_absolute()
      or any(part in ("", ".", "..") for part in relative.parts)
    ):
      raise RequestError(HTTPStatus.NOT_FOUND, "not_found", "static file not found")
    candidate = (self.server.static_directory / Path(*relative.parts)).resolve()
    try:
      candidate.relative_to(self.server.static_directory)
    except ValueError as error:
      raise RequestError(
        HTTPStatus.NOT_FOUND,
        "not_found",
        "static file not found",
      ) from error
    if not candidate.is_file():
      raise RequestError(HTTPStatus.NOT_FOUND, "not_found", "static file not found")
    try:
      data = candidate.read_bytes()
    except OSError as error:
      raise RequestError(
        HTTPStatus.NOT_FOUND,
        "not_found",
        "static file not found",
      ) from error
    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type in (
      "application/javascript",
      "application/json",
    ):
      content_type = f"{content_type}; charset=utf-8"
    self._send_bytes(
      HTTPStatus.OK,
      data,
      content_type,
      cache_control="no-cache",
      head_only=head_only,
    )

  @staticmethod
  def _encode_json(payload: object) -> bytes:
    return json.dumps(
      payload,
      ensure_ascii=False,
      allow_nan=False,
      separators=(",", ":"),
    ).encode("utf-8")

  def _send_json(
    self,
    status: HTTPStatus,
    payload: object,
    *,
    head_only: bool = False,
  ) -> None:
    self._send_json_bytes(status, self._encode_json(payload), head_only=head_only)

  def _send_json_bytes(
    self,
    status: HTTPStatus,
    body: bytes,
    *,
    head_only: bool = False,
  ) -> None:
    self._send_bytes(
      status,
      body,
      "application/json; charset=utf-8",
      cache_control="no-store",
      head_only=head_only,
    )

  def _send_error_json(
    self,
    status: HTTPStatus,
    code: str,
    message: str,
    *,
    head_only: bool = False,
  ) -> None:
    self._send_json(
      status,
      {"error": {"code": code, "message": message}},
      head_only=head_only,
    )

  def _send_method_not_allowed(self, allow: str, *, head_only: bool = False) -> None:
    body = self._encode_json(
      {"error": {"code": "method_not_allowed", "message": "method not allowed"}}
    )
    self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
    self.send_header("Allow", allow)
    self._send_common_headers(
      content_type="application/json; charset=utf-8",
      content_length=len(body),
      cache_control="no-store",
    )
    self.end_headers()
    if not head_only:
      self._write_body(body)

  def _send_bytes(
    self,
    status: HTTPStatus,
    body: bytes,
    content_type: str,
    *,
    cache_control: str,
    head_only: bool,
  ) -> None:
    self.send_response(status)
    self._send_common_headers(
      content_type=content_type,
      content_length=len(body),
      cache_control=cache_control,
    )
    self.end_headers()
    if not head_only:
      self._write_body(body)

  def _send_common_headers(
    self,
    *,
    content_type: str,
    content_length: int,
    cache_control: str,
  ) -> None:
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(content_length))
    self.send_header("Cache-Control", cache_control)
    self.send_header("Pragma", "no-cache")
    self.send_header("X-Content-Type-Options", "nosniff")
    self.send_header("X-Frame-Options", "DENY")
    self.send_header("Referrer-Policy", "no-referrer")
    self.send_header("Cross-Origin-Resource-Policy", "same-origin")
    self.send_header("Cross-Origin-Opener-Policy", "same-origin")
    self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    self.send_header(
      "Content-Security-Policy",
      "default-src 'self'; script-src 'self'; style-src 'self'; "
      "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
      "base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
    )

  def _write_body(self, body: bytes) -> None:
    try:
      self.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
      return


def create_server(
  backend: Any,
  *,
  host: str = DEFAULT_HOST,
  port: int = DEFAULT_PORT,
  static_directory: str | Path = DEFAULT_STATIC_DIRECTORY,
  recorder: Any = None,
) -> SimulatorHTTPServer:
  """Create a bound simulator HTTP server without entering its event loop."""
  if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65_535:
    raise ValueError("port must be an integer from 0 to 65535")
  try:
    address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0][0]
  except socket.gaierror as error:
    raise ValueError(f"cannot resolve host {host!r}: {error}") from error
  server_class = IPv6SimulatorHTTPServer if address == socket.AF_INET6 else SimulatorHTTPServer
  return server_class((host, port), backend, Path(static_directory), recorder)
