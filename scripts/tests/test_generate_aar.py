"""Offline CLI output and invalid input behavior, without a service process."""

import importlib.util
import json
from pathlib import Path

from orchestrator.aar import build_bundle, build_report, render_markdown

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "generate_aar", ROOT / "scripts/generate_aar.py"
)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_offline_markdown_and_json_match_library(tmp_path, capsys):
    exported = build_bundle(
        exercise_id="exercise",
        run_id="run",
        scenario_id="test",
        run_state="stopped",
        checkpoint_ids=["DP1"],
        events=[],
        submissions=[],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(exported), encoding="utf-8")
    assert cli.main([str(path)]) == 0
    assert capsys.readouterr().out == render_markdown(build_report(exported))
    assert cli.main([str(path), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == build_report(exported)
    assert cli.main([str(path), "--format", "feedback"]) == 1
    assert "all five" in capsys.readouterr().err


def test_invalid_and_missing_bundle_fail_without_traceback(tmp_path, capsys):
    path = tmp_path / "invalid.json"
    assert cli.main([str(path)]) == 1
    path.write_text("{", encoding="utf-8")
    assert cli.main([str(path)]) == 1
    path.write_text("[]", encoding="utf-8")
    assert cli.main([str(path)]) == 1
    assert "Traceback" not in capsys.readouterr().err
