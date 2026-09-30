"""Portable exports for facilitator review and downstream SIEM ingestion."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.events import EventValidator, redact_sensitive


CSV_FIELDS = (
    "timestamp",
    "exercise_id",
    "run_id",
    "sequence",
    "event_id",
    "event_type",
    "phase",
    "source_kind",
    "source_component",
    "actor_type",
    "actor_id",
    "action",
    "target_type",
    "target_id",
    "outcome_status",
    "severity",
    "visibility",
    "checkpoint_id",
    "objective_ids",
    "message",
)


def _validated(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    validator = EventValidator()
    result = []
    for event in events:
        sanitized = redact_sensitive(dict(event))
        validator.validate(sanitized)
        result.append(sanitized)
    return sorted(result, key=lambda item: (item["run_id"], item["sequence"]))


def export_jsonl(events: Iterable[Mapping[str, Any]], path: Path | str) -> Path:
    """Write validated canonical events as replayable JSON Lines."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as export_file:
        for event in _validated(events):
            json.dump(event, export_file, sort_keys=True, separators=(",", ":"))
            export_file.write("\n")
    return output


def export_csv(events: Iterable[Mapping[str, Any]], path: Path | str) -> Path:
    """Write a flattened convenience view without replacing canonical JSONL."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as export_file:
        writer = csv.DictWriter(export_file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for event in _validated(events):
            actor = event["actor"]
            target = event.get("target") or {}
            writer.writerow(
                {
                    "timestamp": event["timestamp"],
                    "exercise_id": event["exercise_id"],
                    "run_id": event["run_id"],
                    "sequence": event["sequence"],
                    "event_id": event["event_id"],
                    "event_type": event["event_type"],
                    "phase": event["phase"],
                    "source_kind": event["source"]["kind"],
                    "source_component": event["source"]["component"],
                    "actor_type": actor["type"],
                    "actor_id": actor["id"],
                    "action": event["action"],
                    "target_type": target.get("type", ""),
                    "target_id": target.get("id", ""),
                    "outcome_status": event["outcome"]["status"],
                    "severity": event["severity"],
                    "visibility": event["visibility"],
                    "checkpoint_id": event.get("checkpoint_id") or "",
                    "objective_ids": ";".join(event.get("objective_ids", [])),
                    "message": event["message"],
                }
            )
    return output
