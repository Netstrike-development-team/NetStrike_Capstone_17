"""Adapter from the issue #49 legacy event shape to event contract v1."""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Mapping

from .events import EventBuilder, EventContext, entity

LEGACY_PHASE_MAP = {
    0: "control",
    1: "reconnaissance",
    2: "identity",
    3: "identity",
    4: "identity",
    5: "endpoint_ad",
    6: "cloud",
    7: "impact_recovery",
}

_ATTACK_TECHNIQUE = re.compile(r"^T[0-9]{4}(?:\.[0-9]{3})?$")


def _legacy_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_tactic(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return normalized or None


def _valid_uuid(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def migrate_legacy_event(
    legacy: Mapping[str, Any],
    *,
    context: EventContext,
    sequence: int,
) -> dict[str, Any]:
    """Convert one legacy event while preserving its evidence as redacted data."""

    if sequence < 1:
        raise ValueError("sequence must be at least 1")

    legacy_phase = legacy.get("phase")
    try:
        phase_number = int(legacy_phase)
    except (TypeError, ValueError):
        phase_number = 0
    phase = LEGACY_PHASE_MAP.get(phase_number, "control")

    component = str(legacy.get("source_module") or context.source_component).lower()
    component = re.sub(r"[^a-z0-9._-]+", "-", component).strip("-") or "legacy-module"
    migrated_context = replace(
        context,
        source_kind="module",
        source_component=component,
    )
    builder = EventBuilder(migrated_context, start_sequence=sequence - 1)

    technique_id = legacy.get("technique_id")
    tactic = _safe_tactic(legacy.get("tactic"))
    attack_kwargs: dict[str, str] = {}
    if isinstance(technique_id, str) and _ATTACK_TECHNIQUE.fullmatch(technique_id) and tactic:
        attack_kwargs = {
            "attack_technique_id": technique_id,
            "attack_tactic": tactic,
        }

    status = "error" if phase_number == 0 or tactic == "error" else "success"
    original_id = legacy.get("event_id")
    preserved_event_id = _valid_uuid(original_id)

    return builder.build(
        event_type="legacy.module_event",
        phase=phase,
        actor=entity("system", component),
        action="legacy_event.import",
        target=entity("module", component),
        outcome_status=status,
        message=str(legacy.get("description") or "Migrated legacy module event"),
        severity="high" if status == "error" else "info",
        visibility="internal" if status == "error" else "participant",
        dry_run=False,
        within_allowlist=True,
        safety_controls=("legacy-adapter", "simulation-only"),
        data={
            "legacy_phase": legacy_phase,
            "flag_triggered": legacy.get("flag_triggered"),
            "raw_data": legacy.get("raw_data") or {},
        },
        source_event_id=str(original_id) if original_id is not None else None,
        timestamp=_legacy_timestamp(legacy.get("timestamp")),
        event_id=preserved_event_id,
        **attack_kwargs,
    )
