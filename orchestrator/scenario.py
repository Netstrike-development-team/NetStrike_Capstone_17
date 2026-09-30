"""Versioned, validated scenario definitions for the NetStrike controller."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class ScenarioDefinitionError(ValueError):
    """Raised when a scenario definition is unsafe or internally inconsistent."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_EVENT_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VERSION = re.compile(r"^1\.[0-9]+\.[0-9]+$")
_ITEM_KINDS = frozenset({"setup", "inject", "action", "checkpoint", "end"})
_DELIVERY_MODES = frozenset({"automatic", "facilitator"})
_TRIGGER_TYPES = frozenset({"pre_exercise", "elapsed", "checkpoint"})
_PHASES = frozenset(
    {
        "setup",
        "reconnaissance",
        "identity",
        "endpoint_ad",
        "cloud",
        "impact_recovery",
        "control",
        "post_exercise",
    }
)
_VISIBILITIES = frozenset({"participant", "facilitator", "evaluator", "internal"})


def _required_string(data: Mapping[str, Any], name: str) -> str:
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ScenarioDefinitionError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class ScenarioTrigger:
    """A deterministic trigger supported by the MVP scenario engine."""

    trigger_type: str
    seconds: int | None = None
    checkpoint_id: str | None = None
    checkpoint_outcome: str | None = None
    order: int = 0

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScenarioTrigger":
        trigger_type = _required_string(value, "type")
        if trigger_type not in _TRIGGER_TYPES:
            raise ScenarioDefinitionError(f"unsupported trigger type: {trigger_type}")

        order = value.get("order", 0)
        if not isinstance(order, int) or order < 0:
            raise ScenarioDefinitionError("trigger order must be a non-negative integer")

        if trigger_type == "elapsed":
            seconds = value.get("seconds")
            if not isinstance(seconds, int) or seconds < 0:
                raise ScenarioDefinitionError(
                    "elapsed triggers require non-negative integer seconds"
                )
            return cls(trigger_type=trigger_type, seconds=seconds, order=order)

        if trigger_type == "checkpoint":
            checkpoint_id = _required_string(value, "checkpoint_id")
            outcome = _required_string(value, "outcome")
            if not re.fullmatch(r"DP[1-9][0-9]*", checkpoint_id):
                raise ScenarioDefinitionError("checkpoint_id must look like DP1")
            if outcome not in {"pass", "miss"}:
                raise ScenarioDefinitionError("checkpoint outcome must be pass or miss")
            return cls(
                trigger_type=trigger_type,
                checkpoint_id=checkpoint_id,
                checkpoint_outcome=outcome,
                order=order,
            )

        return cls(trigger_type=trigger_type, order=order)


@dataclass(frozen=True)
class ScenarioItem:  # pylint: disable=too-many-instance-attributes
    """One allowlisted setup task, inject, action, checkpoint, or end marker."""

    item_id: str
    kind: str
    title: str
    summary: str
    phase: str
    delivery: str
    visibility: str
    trigger: ScenarioTrigger
    action_id: str | None = None
    objective_ids: tuple[str, ...] = ()
    checkpoint_id: str | None = None
    participant_prompt: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScenarioItem":
        item_id = _required_string(value, "id")
        kind = _required_string(value, "kind")
        title = _required_string(value, "title")
        summary = _required_string(value, "summary")
        phase = _required_string(value, "phase")
        delivery = _required_string(value, "delivery")
        visibility = _required_string(value, "visibility")

        if not _IDENTIFIER.fullmatch(item_id):
            raise ScenarioDefinitionError(f"invalid item id: {item_id}")
        if kind not in _ITEM_KINDS:
            raise ScenarioDefinitionError(f"unsupported item kind: {kind}")
        if phase not in _PHASES:
            raise ScenarioDefinitionError(f"unsupported phase: {phase}")
        if delivery not in _DELIVERY_MODES:
            raise ScenarioDefinitionError(f"unsupported delivery mode: {delivery}")
        if visibility not in _VISIBILITIES:
            raise ScenarioDefinitionError(f"unsupported visibility: {visibility}")

        raw_trigger = value.get("trigger")
        if not isinstance(raw_trigger, Mapping):
            raise ScenarioDefinitionError(f"{item_id} requires a trigger object")
        trigger = ScenarioTrigger.from_dict(raw_trigger)

        action_id = value.get("action_id")
        if action_id is not None and (
            not isinstance(action_id, str) or not _EVENT_NAME.fullmatch(action_id)
        ):
            raise ScenarioDefinitionError(f"invalid action_id for {item_id}")
        if kind in {"setup", "action"} and delivery == "automatic" and not action_id:
            raise ScenarioDefinitionError(
                f"automatic {kind} item {item_id} requires an action_id"
            )

        objective_ids = value.get("objective_ids", [])
        if not isinstance(objective_ids, list) or not all(
            isinstance(item, str) and re.fullmatch(r"LO[1-9][0-9]*", item)
            for item in objective_ids
        ):
            raise ScenarioDefinitionError(f"invalid objective_ids for {item_id}")

        checkpoint_id = value.get("checkpoint_id")
        if checkpoint_id is not None and (
            not isinstance(checkpoint_id, str)
            or not re.fullmatch(r"DP[1-9][0-9]*", checkpoint_id)
        ):
            raise ScenarioDefinitionError(f"invalid checkpoint_id for {item_id}")
        if kind == "checkpoint" and checkpoint_id != item_id:
            raise ScenarioDefinitionError(
                f"checkpoint item {item_id} must use the same checkpoint_id"
            )

        prompt = value.get("participant_prompt")
        if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
            raise ScenarioDefinitionError(
                f"participant_prompt for {item_id} must be a non-empty string"
            )

        return cls(
            item_id=item_id,
            kind=kind,
            title=title,
            summary=summary,
            phase=phase,
            delivery=delivery,
            visibility=visibility,
            trigger=trigger,
            action_id=action_id,
            objective_ids=tuple(dict.fromkeys(objective_ids)),
            checkpoint_id=checkpoint_id,
            participant_prompt=prompt,
        )


@dataclass(frozen=True)
class ScenarioDefinition:
    """An immutable scenario loaded from a reviewed JSON file."""

    schema_version: str
    scenario_id: str
    exercise_id: str
    name: str
    items: tuple[ScenarioItem, ...]
    participant_experience: Mapping[str, Any]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ScenarioDefinition":
        schema_version = _required_string(value, "schema_version")
        scenario_id = _required_string(value, "scenario_id")
        exercise_id = _required_string(value, "exercise_id")
        name = _required_string(value, "name")
        if not _VERSION.fullmatch(schema_version):
            raise ScenarioDefinitionError("only scenario schema major version 1 is supported")
        if not _IDENTIFIER.fullmatch(scenario_id) or not _IDENTIFIER.fullmatch(exercise_id):
            raise ScenarioDefinitionError("scenario_id and exercise_id are invalid")

        participant_experience = value.get("participant_experience", {})
        if not isinstance(participant_experience, Mapping):
            raise ScenarioDefinitionError(
                "participant_experience must be an object"
            )

        raw_items = value.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise ScenarioDefinitionError("scenario requires at least one item")
        if not all(isinstance(item, Mapping) for item in raw_items):
            raise ScenarioDefinitionError("every scenario item must be an object")
        items = tuple(ScenarioItem.from_dict(item) for item in raw_items)
        ids = [item.item_id for item in items]
        if len(ids) != len(set(ids)):
            raise ScenarioDefinitionError("scenario item ids must be unique")

        checkpoint_ids = {
            item.checkpoint_id for item in items if item.kind == "checkpoint"
        }
        for item in items:
            if (
                item.trigger.trigger_type == "checkpoint"
                and item.trigger.checkpoint_id not in checkpoint_ids
            ):
                raise ScenarioDefinitionError(
                    f"{item.item_id} references an unknown checkpoint"
                )

        return cls(
            schema_version=schema_version,
            scenario_id=scenario_id,
            exercise_id=exercise_id,
            name=name,
            items=items,
            participant_experience=deepcopy(dict(participant_experience)),
        )


def load_scenario(path: Path | str) -> ScenarioDefinition:
    """Load and validate a versioned scenario JSON document."""

    scenario_path = Path(path)
    try:
        with scenario_path.open(encoding="utf-8") as scenario_file:
            value = json.load(scenario_file)
    except json.JSONDecodeError as exc:
        raise ScenarioDefinitionError(
            f"invalid JSON in {scenario_path}: {exc.msg}"
        ) from exc
    if not isinstance(value, Mapping):
        raise ScenarioDefinitionError("scenario root must be an object")
    return ScenarioDefinition.from_dict(value)
