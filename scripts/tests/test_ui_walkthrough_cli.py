"""Recording CLI stays inert by default and refuses artifact overwrites."""

import json
import subprocess
import sys
from pathlib import Path

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
