"""Read-only, explicitly projected local exercise evidence (not a SIEM)."""

from __future__ import annotations

from typing import Any, Mapping

SIGNAL_PREFIXES = ("identity.", "helpdesk.", "endpoint.", "directory.",
                   "cloud.", "impact.", "recovery.")
OWN_RECEIPTS = frozenset({"action.execution.completed", "action.authorization.denied",
                          "action.result.replayed"})
FACT_KEYS = frozenset({
    "source_ip", "host", "identity_id", "factor_id", "ticket_id", "callback_verified",
    "identity_event_id", "category", "command_id", "account_id", "group", "task_id",
    "active", "fixture_id", "synthetic", "originals_unchanged", "backup_intact",
    "available_originals", "marker_count", "note_present", "baseline_verified",
    "encryption_performed", "confirmed_records", "confirmed_count", "record_count",
    "bucket_id", "principal_id", "key_id", "status", "operation", "external_transfer",
})


def project_signal(event: Mapping[str, Any], actor_id: str) -> dict[str, Any] | None:
    """Release module facts or one's own action receipt, never grading/control data."""
    event_type = event["event_type"]
    own_receipt = (
        event.get("visibility") == "facilitator"
        and event_type in OWN_RECEIPTS
        and event["source"]["kind"] == "action_adapter"
        and event["actor"]["id"] == actor_id
        and event["actor"]["type"] == "participant"
    )
    public_signal = (
        event.get("visibility") == "participant"
        and event_type.startswith(SIGNAL_PREFIXES)
    )
    if not (own_receipt or public_signal):
        return None
    facts = {
        key: value for key, value in event.get("data", {}).items()
        if key in FACT_KEYS and isinstance(value, (str, int, float, bool))
        and (not isinstance(value, str) or len(value) <= 512)
    }
    category = "response" if own_receipt else event_type.split(".", 1)[0]
    if category in {"helpdesk", "identity"}:
        category = "identity"
    elif category in {"endpoint", "directory"}:
        category = "endpoint"
    elif category in {"impact", "recovery"}:
        category = "recovery"
    return {
        "event_id": event["event_id"], "sequence": event["sequence"],
        "timestamp": event["timestamp"], "event_type": event_type,
        "category": category, "source": event["source"]["component"],
        "message": event["message"], "outcome": event["outcome"]["status"],
        "actor_id": event["actor"]["id"],
        "target_id": (event.get("target") or {}).get("id"),
        "target_type": (event.get("target") or {}).get("type"),
        "dry_run": event["safety"]["dry_run"], "facts": facts,
    }
