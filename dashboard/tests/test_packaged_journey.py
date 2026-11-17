"""Exercise the packaged journey against real local app routes, not fake results."""

from pathlib import Path
import os
import pytest

from fastapi.testclient import TestClient

from dashboard import offline_smoke
from dashboard.app import create_default_app

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("recovery_mode", ["fixture", "native_files"])
def test_representative_http_journey_and_both_publications(tmp_path, monkeypatch, recovery_mode):
    work = tmp_path / "application"
    work.mkdir()
    (work / "fixtures").mkdir()
    for key in list(os.environ):
        if key.startswith("NETSTRIKE_"):
            monkeypatch.delenv(key)
    # Restore all process configuration after exercising the worker's real setup.
    with monkeypatch.context() as context:
        context.setattr(offline_smoke.os, "environ", dict(offline_smoke.os.environ))
        tokens = offline_smoke.environment(ROOT, work, recovery_mode=recovery_mode)
        with TestClient(create_default_app()) as client:
            result = offline_smoke.journey(client, tokens, work, native_files=recovery_mode == "native_files")
            published = offline_smoke.publication(work)
    assert result["application_reset_verified"] and result["archive_preserved"]
    assert published["canonical_events"] > published["learner_events"] > 0
    assert published["publication_retry_verified"]
    assert published["learner_comparison_verified"]
    assert (tmp_path / "learner-comparison-smoke.json").is_file()
    assert not published["splunk_ingestion_verified"]
    assert result["native_file_recovery_verified"] == (recovery_mode == "native_files")
    assert not result["windows_access_verified"]
    assert (tmp_path / "learner-audit.jsonl").is_file()
