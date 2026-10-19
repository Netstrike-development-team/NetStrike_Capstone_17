"""Synthetic packaged-application HTTP journey, never live range acceptance.

Developer tooling only. The bundle driver invokes this with the bundled Python
in an isolated network namespace; it is not imported by the production app.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time

EXERCISE = "operation-silent-spider"
INITIAL = "offline-smoke-initial"
FRESH = "offline-smoke-after-reset"
ROLES = ("facilitator", "soc_analyst", "identity_responder", "cloud_responder", "evaluator")


class CheckFailure(ValueError):
    """Only fixed developer check codes, never raw provider exceptions."""


def require(condition, code):
    if not condition:
        raise CheckFailure(code)


def save(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def imported_sources(source):
    """Reject accidental imports from checkout, user site or host environments."""
    allowed = (source.resolve(), Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve())
    for module in tuple(sys.modules.values()):
        filename = getattr(module, "__file__", None)
        if filename and not filename.startswith("<"):
            path = Path(filename).resolve()
            require(any(path.is_relative_to(root) for root in allowed), "import_outside_bundle")


def environment(source, work):
    """Synthetic per-process configuration; never retain credentials in evidence."""
    tokens = {role: secrets.token_urlsafe(32) for role in ROLES}
    for key in list(os.environ):
        if key.startswith("NETSTRIKE_"):
            del os.environ[key]
    settings = {
        "NETSTRIKE_PORTAL_TOKENS": json.dumps({token: {"actor_id": "smoke-" + role, "role": role} for role, token in tokens.items()}),
        "NETSTRIKE_IDENTITY_AUDIT_KEY": secrets.token_hex(32),
        "NETSTRIKE_RUN_ID": INITIAL,
        "NETSTRIKE_EXPECTED_SCENARIO_SCOPE": "full-play",
        "NETSTRIKE_SCENARIO_PATH": str(source / "orchestrator/scenarios/full-play.v1.json"),
        "NETSTRIKE_PROFILE_FIXTURE": str(source / "orchestrator/fixtures/identity-profiles.v1.json"),
        "NETSTRIKE_IMPACT_ROOT": str(work / "fixtures"),
        "NETSTRIKE_PORTAL_DATABASE": str(work / "portal.sqlite3"),
        "NETSTRIKE_SSO_ALLOWED_ORIGINS": json.dumps(["http://127.0.0.1"]),
    }
    os.environ.update(settings)
    return tokens


def journey(client, tokens, work):
    """Use only real HTTP endpoints, including authentication and stale-run guards."""
    run_id, checks = INITIAL, []

    def request(method, path, *, role="facilitator", body=None, status=200, extra=None):
        headers = {"Authorization": "Bearer " + tokens[role], "X-Exercise-Run-ID": run_id}
        headers.update(extra or {})
        response = client.request(method, path, headers=headers, json=body)
        require(response.status_code == status, "http_contract:" + path)
        checks.append({"endpoint": path, "status": status})
        return response

    require(client.get("/health").status_code == 200, "health")
    require(client.get("/api/participant/state").status_code == 401, "authentication")
    request("GET", "/api/facilitator/state", role="soc_analyst", status=403)
    for path in ("/participant", "/facilitator", "/evaluator", "/evidence", "/sso",
                 "/static/participant.js", "/static/facilitator.js", "/static/styles.css"):
        require(client.get(path, headers={"Origin": "http://127.0.0.1"}).status_code == 200, "packaged_asset")
    ready = request("GET", "/api/facilitator/readiness").json()
    require(ready["ready_to_prepare"] and not ready["external_readiness_verified"], "readiness")
    request("POST", "/api/facilitator/start", status=409, extra={"X-Exercise-Run-ID": "stale-run"})
    for operation in ("prepare", "start", "pause", "resume"):
        request("POST", "/api/facilitator/" + operation)
    request("POST", "/api/facilitator/advance", body={"elapsed_seconds": 1500})
    signals = request("GET", "/api/participant/evidence", role="soc_analyst").json()["signals"]
    identity = [s for s in signals if s["event_type"].startswith("identity.")]
    helpdesk = [s for s in signals if s["event_type"].startswith("helpdesk.")]
    require(len(identity) >= 2 and helpdesk and len(signals) >= 6, "triage_evidence")
    request("POST", "/api/participant/checkpoints/dp1", role="soc_analyst", body={
        "affected_identity": "sarah", "classification": "account compromise",
        "evidence": [{"reference_id": s["event_id"], "source": origin}
                     for s, origin in ((identity[0], "identity"), (identity[1], "identity"), (helpdesk[0], "helpdesk"))],
    })
    request("POST", "/api/participant/timeline", role="soc_analyst", body={
        "run_id": run_id, "entries": [{"occurred_at": s["timestamp"], "event_id": s["event_id"],
            "statement_type": "fact", "summary": "Synthetic packaged smoke observation."}
            for s in sorted(signals[:6], key=lambda item: (item["timestamp"], item["sequence"]))],
    })
    action = {"action_id": "identity.session.revoke", "target_type": "session", "target_id": "sess-red-01",
              "idempotency_key": "packaged-preview", "dry_run": True}
    request("POST", "/api/participant/actions", role="identity_responder", body=action)
    request("POST", "/api/participant/actions", role="identity_responder", status=403,
            body={**action, "target_id": "not-an-exercise-session", "idempotency_key": "packaged-rejected"})
    request("POST", "/api/participant/actions", role="identity_responder",
            body={**action, "dry_run": False, "idempotency_key": "packaged-execute"})
    for seconds, checkpoint in ((3600, "dp2"), (5700, "dp3"), (6600, "dp4")):
        request("POST", "/api/facilitator/advance", body={"elapsed_seconds": seconds})
        result = request("POST", "/api/facilitator/checkpoints/" + checkpoint).json()
        require(not result["evaluation"]["passed"], "intentional_missed_response")
    request("GET", "/api/participant/cloud", role="cloud_responder")
    recovery = request("GET", "/api/participant/recovery", role="cloud_responder").json()
    require(recovery["fixture"]["available_originals"] == 0, "impact_observed")
    for preview in (True, False):
        request("POST", "/api/participant/recovery/action", role="cloud_responder", body={
            "action_id": "recovery.fixture.restore", "fixture_id": "FILE01-disposable-fixture",
            "key": "packaged-restore-" + str(preview), "dry_run": preview})
        state = request("GET", "/api/participant/recovery", role="cloud_responder").json()
        require(state["fixture"]["available_originals"] == (0 if preview else 5), "recovery_preview_or_execute")
    request("POST", "/api/participant/recovery/action", role="cloud_responder", body={
        "action_id": "recovery.health.validate", "fixture_id": "FILE01-disposable-fixture",
        "key": "packaged-health", "dry_run": False})
    request("POST", "/api/facilitator/stop", body={"reason": "Synthetic packaged smoke complete, not learner evaluation."})
    review = request("GET", "/api/evaluator/exports/bundle.json", role="evaluator").json()
    save(work.parent / "run-review-bundle.json", review)
    raw = request("GET", "/api/facilitator/exports/events.jsonl").text
    with (work.parent / "events.jsonl").open("x", encoding="utf-8") as handle:
        handle.write(raw)
    reset = request("POST", "/api/facilitator/reset", body={"new_run_id": FRESH}).json()
    archive_id = reset["reset"]["review_archive_id"]
    archived = request("GET", f"/api/evaluator/archives/{archive_id}/bundle.json", role="evaluator").content
    run_id = FRESH
    request("POST", "/api/facilitator/start")
    request("POST", "/api/facilitator/stop", body={"reason": "Synthetic fresh-run smoke stopped."})
    require(request("GET", f"/api/evaluator/archives/{archive_id}/bundle.json", role="evaluator").content == archived, "immutable_archive")
    save(work.parent / "http-checks.json", checks)
    return {"http_checks": len(checks), "application_reset_verified": True,
            "archive_preserved": True, "representative_journey_only": True}


def publication(work):
    from . import event_spool, learner_spool  # pylint: disable=import-outside-toplevel
    from .learner_audit import project  # pylint: disable=import-outside-toplevel

    staff, learner = work / "staff-spool", work / "learner-spool"
    for _ in range(20):
        if not event_spool.export(work / "portal.sqlite3", staff, exercise_id=EXERCISE, execute=True)["events_remaining"]:
            break
    else:
        raise ValueError("staff_publication_bound")
    report = learner_spool.export(staff, learner, exercise_id=EXERCISE, execute=True)
    require(report["source_batches_remaining"] == 0, "learner_publication_bound")
    require(not learner_spool.export(staff, learner, exercise_id=EXERCISE, execute=True)["events_selected"], "idempotent_publication")
    canonical = [json.loads(line) for p in sorted(staff.glob("batch-*/events.jsonl")) for line in p.read_text().splitlines()]
    public = [json.loads(line) for p in sorted(learner.glob("batch-*/events.jsonl")) for line in p.read_text().splitlines()]
    expected = [result for event in canonical if (result := project(event)) is not None]
    require(public == expected and public, "projection_reconciliation")
    require({event["run_id"] for event in public} == {INITIAL, FRESH}, "run_correlation")
    require(any(event["visibility"] != "participant" for event in canonical), "private_source_present")
    with (work.parent / "canonical-events.jsonl").open("x", encoding="utf-8") as handle:
        for event in canonical:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    with (work.parent / "learner-audit.jsonl").open("x", encoding="utf-8") as handle:
        for event in public:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
    return {"canonical_events": len(canonical), "learner_events": len(public),
            "publication_retry_verified": True, "splunk_ingestion_verified": False}


def run(bundle, output, revision, inventory_sha256):
    require(sys.flags.isolated and sys.dont_write_bytecode, "isolated_interpreter_required")
    require(sys.prefix == sys.base_prefix and Path(sys.prefix).resolve().is_relative_to(output.resolve() / "runtime"), "packaged_interpreter_required")
    # Third-party/application imports happen only in the packaged interpreter.
    import httpx  # pylint: disable=import-outside-toplevel
    import uvicorn  # pylint: disable=import-outside-toplevel
    from .app import create_default_app  # pylint: disable=import-outside-toplevel
    from .configuration import inspect_configuration  # pylint: disable=import-outside-toplevel
    from .release_check import inspect_release  # pylint: disable=import-outside-toplevel

    source = bundle / "source"
    imported_sources(source)
    release = inspect_release(bundle, expected_revision=revision, expected_inventory_sha256=inventory_sha256)
    require(release["source_verified"], "packaged_source_identity")
    save(output / "release-source.json", release)
    work = output / "application"
    work.mkdir(mode=0o700)
    (work / "fixtures").mkdir(mode=0o700)
    tokens = environment(source, work)
    preflight, _configuration = inspect_configuration(expected_scope="full-play")
    require(preflight["configuration_valid"], "packaged_preflight")
    require(not (work / "portal.sqlite3").exists() and not list((work / "fixtures").iterdir()), "read_only_preflight")
    save(output / "preflight.json", preflight)
    app = create_default_app()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False, loop="asyncio", http="h11"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            require(server.started and thread.is_alive(), "http_startup")
            with httpx.Client(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", trust_env=False, timeout=20) as client:
                result = journey(client, tokens, work)
            result.update(publication(work))
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            require(not thread.is_alive(), "http_shutdown")
    imported_sources(source)
    require(inspect_release(bundle, expected_revision=revision, expected_inventory_sha256=inventory_sha256)["source_verified"], "source_unchanged")
    result.update(passed=True, scope="packaged_synthetic_application_smoke", external_readiness_verified=False,
                  source_revision=revision, full_exercise_acceptance=False, packaged_runtime_verified=True)
    save(output / "application-smoke.json", result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--inventory-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        run(args.bundle, args.output, args.revision, args.inventory_sha256)
    except CheckFailure as failure:
        print("Packaged application smoke check failed: " + str(failure), file=sys.stderr)
        return 1
    except Exception:
        print("Packaged application smoke failed; preserve private diagnostics.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
