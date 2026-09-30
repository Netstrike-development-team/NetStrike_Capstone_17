"""Scenario definition validation tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.scenario import ScenarioDefinition, ScenarioDefinitionError, load_scenario


SCENARIO_PATH = (
    Path(__file__).resolve().parents[1] / "scenarios" / "identity-slice.v1.json"
)


def test_identity_slice_loads_with_expected_boundary() -> None:
    scenario = load_scenario(SCENARIO_PATH)

    assert scenario.schema_version == "1.0.0"
    assert scenario.exercise_id == "operation-silent-spider"
    assert scenario.participant_experience["sso"]["identity"]["id"] == "sarah"
    assert scenario.participant_experience["sso"]["service_name"] == "SimCorp Access"
    assert scenario.items[0].item_id == "PRE-01"
    assert scenario.items[-1].item_id == "ACT-04B"
    assert {item.item_id for item in scenario.items if item.kind == "checkpoint"} == {
        "DP1",
        "DP2",
    }


def test_duplicate_ids_are_rejected() -> None:
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    raw["items"].append(raw["items"][0])

    with pytest.raises(ScenarioDefinitionError, match="unique"):
        ScenarioDefinition.from_dict(raw)


def test_unknown_checkpoint_reference_is_rejected() -> None:
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    raw["items"][-1]["trigger"]["checkpoint_id"] = "DP99"

    with pytest.raises(ScenarioDefinitionError, match="unknown checkpoint"):
        ScenarioDefinition.from_dict(raw)


def test_automatic_action_requires_allowlisted_action_id() -> None:
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    del raw["items"][0]["action_id"]

    with pytest.raises(ScenarioDefinitionError, match="requires an action_id"):
        ScenarioDefinition.from_dict(raw)


def test_non_object_item_is_rejected_cleanly() -> None:
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    raw["items"].append("not-an-item")

    with pytest.raises(ScenarioDefinitionError, match="must be an object"):
        ScenarioDefinition.from_dict(raw)


def test_participant_experience_must_be_an_object() -> None:
    raw = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    raw["participant_experience"] = "unsafe inline page"

    with pytest.raises(ScenarioDefinitionError, match="must be an object"):
        ScenarioDefinition.from_dict(raw)
