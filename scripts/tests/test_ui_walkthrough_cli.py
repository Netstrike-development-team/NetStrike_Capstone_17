"""Recording CLI stays inert by default and refuses artifact overwrites."""

import json
import importlib.util
import subprocess
import sys
from pathlib import Path
import wave

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
