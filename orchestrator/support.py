"""Portable validation and staff projection of attributable exercise assistance."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy

LEARNER_ROLES = frozenset({"incident_lead", "soc_analyst", "identity_responder",
                           "endpoint_responder", "cloud_responder"})
STAFF_ROLES = frozenset({"facilitator", "technical_operator", "evaluator"})
OBJECTIVE_IDS = frozenset(f"LO{number}" for number in range(1, 6))
KINDS = frozenset({"hint", "clarification", "platform_issue"})
COMPONENT = "exercise-support"
REQUEST = "exercise.support.requested"
RESPONSE = "exercise.support.responded"
MAX_REQUESTS = 50
MAX_ACTOR_REQUESTS = 10


def text(value, field, maximum=1024):
    """Bound plain human text without echoing invalid values in errors."""
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 and char not in "\n\r\t" for char in value)):
        raise ValueError(f"invalid support {field}")
    return value.strip()


def objectives(values):
    """Staff select actual objective scope; labels never assign a rating."""
    if (not isinstance(values, list) or not 1 <= len(values) <= 5
            or any(not isinstance(value, str) or value not in OBJECTIVE_IDS for value in values)
            or len(values) != len(set(values))):
        raise ValueError("invalid support objective scope")
    return sorted(values)


def support_index(events):
    """Validate ordered request/reply provenance; omit retry keys from staff views."""
    # Keep every provenance/correlation check explicit at the portable evidence boundary.
    # pylint: disable=too-many-locals,too-many-boolean-expressions
    records = {}
    keys = set()
    counts = Counter()
    pending = set()
    scope = None
    last_sequence = 0
    for event in events:
        if event["event_type"] not in {REQUEST, RESPONSE}:
            if event["source"]["component"] == COMPONENT:
                raise ValueError("unknown support event type")
            continue
        data = event["data"]
        actor = event["actor"]
        event_scope = (event["exercise_id"], event["run_id"])
        if scope is None:
            scope = event_scope
        if (scope != event_scope or event["sequence"] <= last_sequence
                or event["source"]["component"] != COMPONENT
                or event["visibility"] != "facilitator"
                or event["phase"] != "control"
                or event["outcome"]["status"] != "success"
                or event["safety"]["dry_run"] is not False
                or not isinstance(data, dict)):
            raise ValueError("invalid support provenance")
        last_sequence = event["sequence"]
        elapsed = data.get("elapsed_seconds")
        if not isinstance(elapsed, int) or isinstance(elapsed, bool) or elapsed < 0:
            raise ValueError("invalid support exercise time")
        content = text(data.get("text"), "text")
        if event["event_type"] == REQUEST:
            fields = {"request_key", "objective_id", "text", "elapsed_seconds", "run_state"}
            objective = data.get("objective_id")
            if (set(data) != fields or actor["type"] != "participant"
                    or actor.get("role") not in LEARNER_ROLES
                    or event["source"]["kind"] != "participant"
                    or not isinstance(objective, str) or objective not in OBJECTIVE_IDS
                    or event.get("objective_ids") != [objective]
                    or data["run_state"] not in {"running", "paused"}
                    or event["action"] != "exercise.support.request"
                    or event["target"] != {"type": "support_queue", "id": event["run_id"]}
                    or actor["id"] in pending or event["event_id"] in records):
                raise ValueError("invalid support request")
            key = (REQUEST, actor["id"], text(data["request_key"], "retry key", 128))
            counts[actor["id"]] += 1
            if counts[actor["id"]] > MAX_ACTOR_REQUESTS or len(records) >= MAX_REQUESTS:
                raise ValueError("support request limit exceeded")
            pending.add(actor["id"])
            records[event["event_id"]] = {
                "request_id": event["event_id"], "requester_id": actor["id"],
                "requester_role": actor["role"], "objective_id": objective,
                "question": content, "requested_at": event["timestamp"],
                "elapsed_seconds": elapsed, "run_state": data["run_state"], "response": None,
            }
        else:
            fields = {"request_id", "response_key", "kind", "text", "elapsed_seconds", "run_state"}
            record = records.get(data.get("request_id"))
            kind = data.get("kind")
            if (set(data) != fields or record is None or record["response"] is not None
                    or actor["type"] != "facilitator"
                    or actor.get("role") not in {"facilitator", "technical_operator"}
                    or actor["role"] == "technical_operator" and kind != "platform_issue"
                    or event["source"]["kind"] != "facilitator" or kind not in KINDS
                    or data["run_state"] not in {"running", "paused", "stopped"}
                    or data["run_state"] == "stopped" and kind != "platform_issue"
                    or elapsed < record["elapsed_seconds"]
                    or event["action"] != "exercise.support.respond"
                    or event["target"] != {"type": "support_request", "id": data["request_id"]}
                    or event["correlation_ids"] != [data["request_id"]]):
                raise ValueError("invalid support response")
            scope_ids = objectives(event.get("objective_ids"))
            key = (RESPONSE, actor["id"], text(data["response_key"], "retry key", 128))
            pending.remove(record["requester_id"])
            record["response"] = {
                "event_id": event["event_id"], "kind": kind, "text": content,
                "objective_ids": scope_ids, "responder_id": actor["id"],
                "responder_role": actor["role"], "responded_at": event["timestamp"],
                "elapsed_seconds": elapsed, "run_state": data["run_state"],
            }
        if key in keys:
            raise ValueError("duplicate support retry key")
        keys.add(key)
    return deepcopy(list(records.values()))


def participant_records(records, actor_id):
    """Only the requester's question and intentional human reply are released."""
    projected = []
    for record in records:
        if record["requester_id"] != actor_id:
            continue
        response = record["response"]
        projected.append({
            key: deepcopy(record[key]) for key in (
                "request_id", "objective_id", "question", "requested_at",
                "elapsed_seconds", "run_state",
            )
        } | {"response": ({key: deepcopy(response[key]) for key in (
            "event_id", "kind", "text", "objective_ids", "responded_at",
            "elapsed_seconds", "run_state",
        )} if response else None)})
    return projected
