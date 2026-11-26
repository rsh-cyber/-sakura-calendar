"""Local HTTP interface for editing the calendar companion's events."""

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading


_MAX_BODY_BYTES = 32 * 1024
_EVENT_KINDS = ("daily", "annual", "custom")
_STATIC = {
    "": ("index.html", "text/html; charset=utf-8"),
    "index.html": ("index.html", "text/html; charset=utf-8"),
    "editor.css": ("editor.css", "text/css; charset=utf-8"),
    "editor.js": ("editor.js", "text/javascript; charset=utf-8"),
}
_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class _RejectedRequest(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class CalendarProfileChanged(ValueError):
    """An edit was submitted from a character other than the active one."""


class _LocalServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # Request paths contain a private token. Never write them to Sakura's logs.
        pass


class CalendarWeb:
    def __init__(self, load_state, save_event, delete_event, *,
                 save_holidays=None, save_settings=None, assets=None):
        asset_root = Path(assets) if assets is not None else Path(__file__).with_name("web")
        prefix = f"/{secrets.token_urlsafe(32)}/"

        class Handler(BaseHTTPRequestHandler):
            server_version = "Calendar"
            sys_version = ""

            def setup(self):
                self.request.settimeout(5)
                super().setup()

            def log_message(self, format, *args):
                pass

            def _write(self, status, content_type, body):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status, message):
                self._write(
                    status,
                    "application/json; charset=utf-8",
                    json.dumps({"error": message}, ensure_ascii=False).encode("utf-8"),
                )

            def _check_access(self, *, mutation=False):
                host = f"127.0.0.1:{self.server.server_port}"
                if self.headers.get_all("Host") != [host]:
                    raise _RejectedRequest(HTTPStatus.FORBIDDEN, "本地编辑地址无效。")
                origins = self.headers.get_all("Origin")
                if mutation and origins is not None and origins != [f"http://{host}"]:
                    raise _RejectedRequest(HTTPStatus.FORBIDDEN, "请求来源无效。")
                if not self.path.startswith(prefix):
                    raise _RejectedRequest(HTTPStatus.NOT_FOUND, "找不到此页面。")
                return self.path[len(prefix):]

            def _read_json(self):
                content_types = self.headers.get_all("Content-Type", [])
                if len(content_types) != 1 or content_types[0].split(";", 1)[0].strip().lower() != "application/json":
                    raise _RejectedRequest(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "请使用 JSON 提交。")
                if "Transfer-Encoding" in self.headers:
                    raise _RejectedRequest(HTTPStatus.BAD_REQUEST, "不支持分块提交。")
                lengths = self.headers.get_all("Content-Length")
                if lengths is None:
                    raise _RejectedRequest(HTTPStatus.LENGTH_REQUIRED, "缺少请求长度。")
                length = lengths[0].strip()
                if len(lengths) != 1 or not (length.isascii() and length.isdecimal()):
                    raise _RejectedRequest(HTTPStatus.BAD_REQUEST, "请求长度无效。")
                if len(length) > 8 or int(length) > _MAX_BODY_BYTES:
                    raise _RejectedRequest(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "请求内容过长。")
                size = int(length)
                try:
                    body = self.rfile.read(size)
                    if len(body) != size:
                        raise ValueError("incomplete body")
                    return json.loads(body.decode("utf-8"))
                except (OSError, ValueError, RecursionError) as error:
                    raise _RejectedRequest(HTTPStatus.BAD_REQUEST, "请求内容不是有效的 JSON。") from error

            def _write_state(self):
                try:
                    state = load_state()
                    if not isinstance(state, dict):
                        raise TypeError("calendar state must be an object")
                    body = json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")
                except Exception:
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "暂时无法读取日历设置。")
                else:
                    self._write(HTTPStatus.OK, "application/json; charset=utf-8", body)

            def do_GET(self):
                try:
                    route = self._check_access()
                    if route == "api/state":
                        self._write_state()
                        return
                    asset = _STATIC.get(route)
                    if asset is None:
                        raise _RejectedRequest(HTTPStatus.NOT_FOUND, "找不到此页面。")
                    name, content_type = asset
                    try:
                        body = (asset_root / name).read_bytes()
                    except FileNotFoundError as error:
                        raise _RejectedRequest(HTTPStatus.NOT_FOUND, "找不到此页面。") from error
                    except OSError as error:
                        raise _RejectedRequest(HTTPStatus.INTERNAL_SERVER_ERROR, "暂时无法读取编辑页面。") from error
                    self._write(HTTPStatus.OK, content_type, body)
                except _RejectedRequest as error:
                    self._error(error.status, str(error))

            def do_POST(self):
                try:
                    route = self._check_access(mutation=True)
                    if (route not in ("api/events", "api/events/delete", "api/holidays", "api/settings")
                            or (route == "api/holidays" and save_holidays is None)
                            or (route == "api/settings" and save_settings is None)):
                        raise _RejectedRequest(HTTPStatus.NOT_FOUND, "找不到此页面。")
                    value = self._read_json()
                    if not isinstance(value, dict):
                        raise ValueError("角色日历设置无效。")
                    character_id = value.pop("characterId", None)
                    if not isinstance(character_id, str) or not character_id.strip():
                        raise ValueError("缺少角色标识，请重新打开日历。")
                    if route == "api/holidays":
                        save_holidays(value, character_id)
                    elif route == "api/settings":
                        if set(value) != {"settings"} or not isinstance(value["settings"], dict):
                            raise ValueError("角色日历设置无效。")
                        save_settings(value["settings"], character_id)
                    elif value.get("kind") not in _EVENT_KINDS:
                        raise ValueError("请选择有效的事项类别。")
                    elif route == "api/events":
                        event = value.get("event")
                        if set(value) != {"kind", "event"} or not isinstance(event, dict):
                            raise ValueError("事项内容无效。")
                        if "id" in event and not (isinstance(event["id"], str) and event["id"].strip()):
                            raise ValueError("事项编号无效。")
                        save_event(value["kind"], event, character_id)
                    else:
                        event_id = value.get("id")
                        if set(value) != {"kind", "id"} or not (isinstance(event_id, str) and event_id.strip()):
                            raise ValueError("事项编号无效。")
                        delete_event(value["kind"], event_id, character_id)
                except _RejectedRequest as error:
                    self._error(error.status, str(error))
                except CalendarProfileChanged as error:
                    self._error(HTTPStatus.CONFLICT, str(error))
                except ValueError as error:
                    self._error(HTTPStatus.BAD_REQUEST, str(error) or "事项内容无效。")
                except Exception:
                    self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "暂时无法保存日历设置。")
                else:
                    self._write_state()

        self._server = _LocalServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}{prefix}"
        self._close_lock = threading.Lock()
        self._closed = False
        self._worker = threading.Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.05},
            name="SakuraCalendarWeb",
            daemon=True,
        )
        try:
            self._worker.start()
        except BaseException:
            self._server.server_close()
            raise

    def close(self):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._server.shutdown()
            self._server.server_close()

