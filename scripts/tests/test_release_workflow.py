"""Regression contracts for the strict milestone check, without external APIs."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/local-rehearsal-ci.yml"


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_dev_and_main_have_the_same_strict_check(event):
    workflow = WORKFLOW.read_text()
    assert re.search(rf"^  {event}:\n    branches: \[dev, main\]$", workflow, re.M)
    assert "  workflow_dispatch:" in workflow
    assert "  full-play-rehearsal:" in workflow  # Preserve the existing check identity.
    assert "paths-ignore:" not in workflow and "paths:" not in workflow


def test_strict_ci_covers_core_tests_and_exact_checkout_without_failure_masking():
    workflow = WORKFLOW.read_text()
    assert "python -m pytest shared/tests dashboard/tests orchestrator/tests scripts/tests citef-config/tests -q" in workflow
    assert "node --test dashboard/tests/*.test.mjs" in workflow
    assert "-r citef-config/requirements-validator.txt" in workflow
    assert 'python scripts/rehearsal.py --verify "$RUNNER_TEMP/local-rehearsal-evidence" --require-current-source' in workflow
    assert 'python scripts/rehearsal.py --execute --output "$RUNNER_TEMP/local-rehearsal-evidence"' in workflow
    assert "--case" not in workflow
    assert "|| true" not in workflow and "continue-on-error" not in workflow
    assert "if: always()" in workflow  # Retain partial artifacts even on failure.
    assert "contents: read" in workflow
    assert "pull_request_target:" not in workflow
    assert "git push" not in workflow and "gh pr merge" not in workflow
