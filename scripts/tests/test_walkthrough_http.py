"""Recorder bearer/payload requests stay local, with no proxies or redirects."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Thread
import urllib.error

import pytest

from scripts import record_ui_walkthrough as recording


@pytest.mark.parametrize("base", [
    None, "file:///private-secret", "https://127.0.0.1:1234", "http://example.invalid:1234",
    "http://localhost:1234", "http://127.0.0.1", "http://127.0.0.1:0", "http://127.0.0.1:65536",
    "http://127.0.0.1:private-secret", "http://user:private-secret@127.0.0.1:1234",
    "http://127.0.0.1:1234/path", "http://127.0.0.1:1234?q=private-secret",
    "http://127.0.0.1:1234#private-secret", "http://127.0.0.1:1234\n", "http://[::1]:1234",
])
def test_bad_origins_fail_before_opener_creation(tmp_path, monkeypatch, base):
    recorder = recording.Walkthrough(tmp_path)
    recorder.base = base

    def forbidden(*_args):
        pytest.fail("invalid URLs must not initialize network handling")

    monkeypatch.setattr(recording.urllib.request, "build_opener", forbidden)
    with pytest.raises(ValueError) as error:
        recorder.request("/health")
    assert "private-secret" not in str(error.value)


@pytest.mark.parametrize("path", [
    None, "health", "https://example.invalid/private-secret", "//example.invalid/private-secret",
    "/health#private-secret", "/health\n", "/health with space", "/\\private-secret", "/é",
])
def test_bad_routes_fail_before_network_use(path):
    with pytest.raises(ValueError) as error:
        recording.local_request_url("http://127.0.0.1:1234", path)
    assert "private-secret" not in str(error.value)


@contextmanager
def local_server(*, redirect=None, code=302):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # pylint: disable=invalid-name
            self.respond()

        def do_POST(self):  # pylint: disable=invalid-name
            self.respond()

        def respond(self):
            length = int(self.headers.get("Content-Length", 0))
            requests.append({"path": self.path, "method": self.command,
                             "authorization": self.headers.get("Authorization"),
                             "body": self.rfile.read(length)})
            if redirect:
                self.send_response(code)
                self.send_header("Location", redirect)
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *_args):
            pass  # Do not print test request headers or synthetic bearer values.

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.parametrize("payload", [None, {"synthetic": "test-payload"}])
def test_loopback_request_ignores_environment_proxy_and_keeps_method_body(tmp_path, monkeypatch, payload):
    for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")
    with local_server() as (base, requests):
        recorder = recording.Walkthrough(tmp_path)
        recorder.base = base
        assert recorder.request("/health?test=1", payload=payload) == {"ok": True}
    assert len(requests) == 1
    assert requests[0]["path"] == "/health?test=1"
    assert requests[0]["authorization"] == "Bearer " + recorder.roles["facilitator"]
    assert requests[0]["method"] == ("GET" if payload is None else "POST")
    assert requests[0]["body"] == (b"" if payload is None else json.dumps(payload).encode())


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("payload", [None, {"synthetic": "test-payload"}])
def test_even_local_redirects_never_forward_bearer_or_payload(tmp_path, code, payload):
    with local_server(redirect="/target", code=code) as (base, requests):
        recorder = recording.Walkthrough(tmp_path)
        recorder.base = base
        with pytest.raises(urllib.error.HTTPError) as error:
            recorder.request("/redirect", payload=payload)
        assert error.value.code == code
        error.value.close()
    assert [request["path"] for request in requests] == ["/redirect"]


@pytest.mark.parametrize("destination", ["https://example.invalid/target", "file:///private-secret"])
def test_external_or_file_redirects_are_denied(tmp_path, destination):
    with local_server(redirect=destination) as (base, requests):
        recorder = recording.Walkthrough(tmp_path)
        recorder.base = base
        with pytest.raises(urllib.error.HTTPError) as error:
            recorder.request("/redirect")
        assert error.value.code == 302
        error.value.close()
    assert len(requests) == 1
