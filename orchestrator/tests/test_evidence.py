"""Evidence export tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from orchestrator.controller import ScenarioController
from orchestrator.evidence import export_csv, export_jsonl, render_csv, render_jsonl
from orchestrator.scenario import load_scenario


SCENARIO_PATH = (
    Path(__file__).resolve().parents[1] / "scenarios" / "identity-slice.v1.json"
)


def test_jsonl_is_canonical_and_csv_is_flattened_view(tmp_path) -> None:
    events = []
    controller = ScenarioController(
        load_scenario(SCENARIO_PATH),
        event_sink=events.append,
        run_id="run-export-test",
    )
    controller.start()

    jsonl_path = export_jsonl(events, tmp_path / "events.jsonl")
    csv_path = export_csv(events, tmp_path / "events.csv")

    json_events = [
        json.loads(line)
        for line in jsonl_path.read_text(encoding="utf-8").splitlines()
    ]
    json_event = json_events[0]
    assert json_event["event_type"] == "scenario.run.started"
    assert json_event["safety"]["simulation_only"] is True
    assert json_events[1]["event_type"] == "scenario.item.delivered"

    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert rows[0]["run_id"] == "run-export-test"
    assert rows[0]["source_component"] == "scenario-controller"
    assert "safety" not in rows[0]

    assert render_jsonl(events) == jsonl_path.read_text(encoding="utf-8")
    assert render_csv(events) == csv_path.read_text(encoding="utf-8")
