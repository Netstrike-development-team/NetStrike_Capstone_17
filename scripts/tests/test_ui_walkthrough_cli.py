"""Recording CLI stays inert by default and refuses artifact overwrites."""

import json
import importlib.util
import subprocess
import sys
from pathlib import Path
import wave
from types import SimpleNamespace
from contextlib import nullcontext

import pytest

from scripts import record_ui_walkthrough as recording
from scripts import rehearsal

SCRIPT = Path(__file__).resolve().parents[1] / "record_ui_walkthrough.py"


def test_preview_requires_no_recording_dependencies_and_makes_no_output(tmp_path):
    destination = tmp_path / "not-created"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(destination)],
        check=True, capture_output=True, text=True,
    )
    preview = json.loads(result.stdout)
    assert preview["preview_only"] and preview["writes_performed"] is False
    assert len(preview["chapters"]) == 18
    assert not destination.exists()


def test_recording_requires_explicit_output():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--execute"], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "requires a new --output" in result.stderr


def test_existing_output_is_not_overwritten(tmp_path):
    artifact = tmp_path / "client-video.mp4"
    artifact.write_bytes(b"existing user artifact")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--execute", "--output", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert "must not already exist" in result.stderr
    assert artifact.read_bytes() == b"existing user artifact"


def test_narration_preparation_uses_valid_wave_suffix_without_external_tools(tmp_path, monkeypatch):
    specification = importlib.util.spec_from_file_location("walkthrough_for_test", SCRIPT)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    (tmp_path / "narration").mkdir()
    recorder = module.Walkthrough(tmp_path)
    recorder.ffmpeg = "test-encoder"

    def fake_tool(command, **_kwargs):
        if command[0] == "say":
            Path(command[-1]).write_bytes(b"synthetic test audio fixture")
        else:
            assert Path(command[-1]).suffix == ".wav"
            with wave.open(command[-1], "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(bytes(9600))

    monkeypatch.setattr(module.shutil, "which", lambda _command: "/test/say")
    monkeypatch.setattr(module, "checked", fake_tool)
    recorder.prepare_audio()
    assert len(recorder.audio) == 18
    assert all(clip["path"].suffix == ".wav" and clip["duration"] == 0.1
               for clip in recorder.audio)


def test_smoke_preview_stays_inert(tmp_path):
    output = tmp_path / "not-created"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--smoke-only", "--output", str(output)],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["writes_performed"] is False
    assert not output.exists()


@pytest.mark.parametrize("existing", [False, True])
def test_smoke_execution_requires_new_explicit_output(tmp_path, existing):
    arguments = [sys.executable, str(SCRIPT), "--execute", "--smoke-only"]
    if existing:
        arguments.extend(["--output", str(tmp_path)])
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("smoke", [False, True])
def test_browser_mode_selects_explicit_channel_and_fast_timing(tmp_path, smoke):
    calls = []
    recorder = recording.Walkthrough(tmp_path, smoke_only=smoke)
    recorder.playwright = SimpleNamespace(chromium=SimpleNamespace(
        launch=lambda **options: calls.append(options)
    ))
    recorder.launch_browser()
    assert calls == ([{"headless": True}] if smoke else [{"headless": True, "channel": "chrome"}])
    assert recorder.fast is smoke
    assert recorder.narrate is not smoke


@pytest.mark.parametrize("smoke", [False, True])
@pytest.mark.parametrize("failure", [None, "context", "journey"])
def test_browser_cleanup_and_media_options(tmp_path, monkeypatch, smoke, failure):
    recorder = recording.Walkthrough(tmp_path, smoke_only=smoke)
    calls = []
    page = SimpleNamespace(video=SimpleNamespace(path=lambda: "recorded.webm"))
    context = SimpleNamespace(new_page=lambda: page, close=lambda: calls.append("context-closed"))

    def new_context(**options):
        assert options["accept_downloads"] is True
        assert ("record_video_dir" in options) is not smoke
        if failure == "context":
            raise RuntimeError("test context failure")
        return context

    browser = SimpleNamespace(version="test-browser", new_context=new_context,
                              close=lambda: calls.append("browser-closed"))
    monkeypatch.setattr(recorder, "launch_browser", lambda: browser)
    monkeypatch.setattr(recorder, "watch_page", lambda _page: None)

    def perform():
        calls.append("journey")
        if failure == "journey":
            raise RuntimeError("test journey failure")

    monkeypatch.setattr(recorder, "perform", perform)
    if failure:
        with pytest.raises(RuntimeError):
            recorder.run_browser()
    else:
        recorder.run_browser()
        assert recorder.video == (None if smoke else "recorded.webm")
    assert calls[-1] == "browser-closed"
    assert ("context-closed" in calls) is (failure != "context")


def test_page_watch_rejects_local_errors_but_allows_deliberate_abort(tmp_path):
    recorder = recording.Walkthrough(tmp_path, smoke_only=True)
    recorder.base = "http://127.0.0.1:1234"
    handlers = {}
    recorder.watch_page(SimpleNamespace(on=lambda name, callback: handlers.update({name: callback})))
    handlers["pageerror"]("test error")
    handlers["response"](SimpleNamespace(url=recorder.base + "/api/test?secret=not-exported", status=503))
    handlers["response"](SimpleNamespace(url=recorder.base + "/ok", status=200))
    handlers["requestfailed"](SimpleNamespace(url=recorder.base + "/cancel", failure="net::ERR_ABORTED"))
    handlers["requestfailed"](SimpleNamespace(url=recorder.base + "/fail", failure="net::ERR_CONNECTION_RESET"))
    assert recorder.console_errors == ["test error"]
    assert recorder.requests_failed == [
        {"path": "/api/test", "status": 503}, {"path": "/fail", "status": "transport_failed"},
    ]


@pytest.mark.parametrize("failure", [False, True])
@pytest.mark.parametrize("force_kill", [False, True])
def test_smoke_execute_needs_no_media_and_cleans_server_state(
    tmp_path, monkeypatch, failure, force_kill
):
    recorder = recording.Walkthrough(tmp_path, smoke_only=True)
    calls = []
    owned = {}
    monkeypatch.setenv("NETSTRIKE_PROFILE_FIXTURE", "/unrelated/private/deployment")
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", SimpleNamespace(
        sync_playwright=lambda: nullcontext("test-playwright")
    ))
    listener = SimpleNamespace(bind=lambda address: calls.append(address),
                               getsockname=lambda: ("127.0.0.1", 1234))
    monkeypatch.setattr(recording.socket, "socket", lambda: nullcontext(listener))

    class Process:
        def __init__(self, command, **options):
            assert command[command.index("--host") + 1] == "127.0.0.1"
            assert "NETSTRIKE_PROFILE_FIXTURE" not in options["env"]
            assert options["env"]["NETSTRIKE_RUN_ID"].startswith("ui-walkthrough-")
            owned["database"] = Path(options["env"]["NETSTRIKE_PORTAL_DATABASE"])
            owned["decoys"] = Path(options["env"]["NETSTRIKE_IMPACT_ROOT"])
            owned["database"].write_bytes(b"disposable test SQLite stand-in")
            assert owned["decoys"].is_dir()

        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, *, timeout):
            calls.append(("wait", timeout))
            if force_kill and timeout == 15:
                raise subprocess.TimeoutExpired("test server", timeout)

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(recording.subprocess, "Popen", Process)
    monkeypatch.setattr(recorder, "request", lambda path: {"ok": path == "/health"})

    def run_browser():
        if failure:
            raise RuntimeError("test browser failure")

    monkeypatch.setattr(recorder, "run_browser", run_browser)
    if failure:
        with pytest.raises(RuntimeError, match="test browser failure"):
            recorder.execute()
    else:
        recorder.execute()
    assert "terminate" in calls
    assert ("kill" in calls) is force_kill
    assert calls[-1] == ("wait", 5 if force_kill else 15)
    assert not owned["database"].exists() and not owned["decoys"].exists()
    assert {path.name for path in tmp_path.iterdir()} == {"frames", "server.log"}


@pytest.mark.parametrize("failure", ["execution", "browser", "http", "source"])
def test_failed_smoke_never_emits_success_receipt(tmp_path, monkeypatch, failure):
    recorder = recording.Walkthrough(tmp_path, smoke_only=True)
    source = {"git_revision": "test", "working_tree_dirty": False, "files_sha256": {}}
    monkeypatch.setattr(rehearsal, "_source", lambda: dict(source))

    def execute():
        if failure == "execution":
            raise RuntimeError("private-token-must-not-be-exported")
        if failure == "browser":
            recorder.console_errors.append("test error")
        if failure == "http":
            recorder.requests_failed.append({"path": "/api/test", "status": 500})
        if failure == "source":
            source["git_revision"] = "changed"

    monkeypatch.setattr(recorder, "execute", execute)
    monkeypatch.setattr(recorder, "smoke_receipt", lambda: pytest.fail("success after failure"))
    with pytest.raises((RuntimeError, AssertionError)):
        recorder.record()
    assert not (tmp_path / "manifest.json").exists()
    failure_text = (tmp_path / "failure.json").read_text()
    assert "private-token" not in failure_text
    assert json.loads(failure_text)["passed"] is False


def test_smoke_receipt_carries_source_artifact_hashes_and_limits(tmp_path, monkeypatch):
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames/01.png").write_bytes(b"test frame")
    (tmp_path / "events.jsonl").write_bytes(b"test canonical events")
    recorder = recording.Walkthrough(tmp_path, smoke_only=True)
    recorder.source = {"git_revision": "test", "working_tree_dirty": False, "files_sha256": {}}
    recorder.browser_version = "test-browser"
    recorder.events_count = 123
    recorder.run_id = "synthetic-test"
    monkeypatch.setattr(recording.importlib.metadata, "version", lambda _: "test-package")
    recorder.smoke_receipt()
    text = (tmp_path / "manifest.json").read_text()
    manifest = json.loads(text)
    assert manifest["passed"] is True
    assert manifest["source"] == recorder.source
    assert manifest["range_acceptance"] is False
    assert manifest["representative_usability_verified"] is False
    assert manifest["mocked_api_responses"] is False
    assert manifest["events_validated"] == 123
    assert set(manifest["files_sha256"]) == {"frames/01.png", "events.jsonl"}
    assert manifest["files_sha256"]["events.jsonl"] == rehearsal._sha(tmp_path / "events.jsonl")
    assert all(token not in text for token in recorder.roles.values())


def test_smoke_ci_is_strict_and_source_inventory_includes_tooling():
    workflow = (rehearsal.ROOT / ".github/workflows/local-rehearsal-ci.yml").read_text()
    smoke_job = workflow.split("  browser-smoke:\n", 1)[1].split("  full-play-rehearsal:", 1)[0]
    assert "--execute --smoke-only" in smoke_job
    assert "playwright install --with-deps chromium" in smoke_job
    assert "requirements-browser-smoke.txt" in smoke_job
    assert "if: always()" in smoke_job and "retention-days: 14" in smoke_job
    assert "continue-on-error" not in smoke_job and "|| true" not in smoke_job
    fingerprints = rehearsal._source()["files_sha256"]
    for name in ("scripts/record_ui_walkthrough.py", "scripts/requirements-browser-smoke.txt",
                 "scripts/tests/test_ui_walkthrough_cli.py", ".github/workflows/local-rehearsal-ci.yml"):
        assert fingerprints[name] == rehearsal._sha(rehearsal.ROOT / name)


@pytest.mark.parametrize("kind,message,accepted", [
    ("confirm", "Reset application run synthetic-test? Existing safety instructions.", True),
    ("confirm", "Reset application run unrelated?", False),
    ("confirm", "Unexpected prompt", False),
    ("alert", "Reset application run synthetic-test?", False),
])
def test_reset_confirmation_never_accepts_unrelated_dialog(tmp_path, kind, message, accepted):
    recorder = recording.Walkthrough(tmp_path, smoke_only=True)
    recorder.run_id = "synthetic-test"
    calls = []
    dialog = SimpleNamespace(type=kind, message=message,
                             accept=lambda: calls.append("accept"),
                             dismiss=lambda: calls.append("dismiss"))
    if accepted:
        recorder.confirm_reset(dialog)
    else:
        with pytest.raises(RuntimeError, match="unexpected reset confirmation"):
            recorder.confirm_reset(dialog)
    assert calls == (["accept"] if accepted else ["dismiss"])
