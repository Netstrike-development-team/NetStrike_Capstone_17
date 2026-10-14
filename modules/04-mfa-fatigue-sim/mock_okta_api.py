"""Legacy action boundary retained for simulator compatibility.

The participant-facing SSO experience is served by ``dashboard`` at ``/sso``.
This module intentionally contains no sign-in page, vendor branding, shared
password, or state-changing compatibility route.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request

from config import API_PORT, APPROVAL_THRESHOLD
from identity_controller import (
    AuthenticationError,
    IdentityController,
    load_token_principals,
)
from shared.actions import ActionContractError
from shared.events import EventLedger


app = Flask(__name__)
event_ledger = EventLedger(
    os.getenv("NETSTRIKE_EVENT_LEDGER", "output/identity_events.jsonl")
)
controller = IdentityController(
    exercise_id=os.getenv("NETSTRIKE_EXERCISE_ID", "silent-spider"),
    run_id=os.getenv("NETSTRIKE_RUN_ID", "local-development"),
    tokens=load_token_principals(),
    event_sink=event_ledger.append,
    approval_threshold=APPROVAL_THRESHOLD,
)


@app.route("/", methods=["GET"])
@app.route("/victim", methods=["GET"])
def retired_participant_ui():
    """Prevent operators from accidentally using the retired unsafe page."""

    return (
        jsonify(
            {
                "error": "Participant UI moved to the exercise dashboard /sso path",
                "component": "legacy-identity-action-api",
            }
        ),
        410,
    )


@app.route("/api/action", methods=["POST"])
def submit_action():
    """Authenticate and submit one server-correlated safe action."""

    try:
        principal = controller.authenticate(request.headers.get("Authorization"))
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("JSON object required")
        result = controller.submit(principal, payload)
    except AuthenticationError as exc:
        return jsonify({"error": str(exc)}), 401
    except (ValueError, TypeError, ActionContractError) as exc:
        return jsonify({"error": str(exc)}), 400

    if result["status"] == "denied":
        response_status = (
            409 if result["error_code"] == "idempotency_conflict" else 403
        )
        return jsonify(result), response_status
    return jsonify(result), 200


@app.route("/api/push", methods=["POST"])
@app.route("/api/human-approve", methods=["POST"])
@app.route("/api/reset", methods=["POST"])
def removed_compatibility_routes():
    """Require all mutations to use the authenticated safe-action boundary."""

    return jsonify({"error": "Use authenticated /api/action"}), 410


if __name__ == "__main__":
    print(f"Identity action API listening on http://localhost:{API_PORT}")
    print("Participant SSO is served by the dashboard /sso path")
    app.run(port=API_PORT, debug=False)
