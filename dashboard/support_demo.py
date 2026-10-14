"""Preview-by-default human support demonstration; no UI, server or network."""

import argparse
import json

from .auth import PortalPrincipal
from .service import PortalService
from .store import PortalStore


def plan():
    """Inert description, without constructing a runtime or producing evidence."""
    return {
        "developer_demo_only": True, "writes_performed": False,
        "automatic_answers": False, "live_range_verified": False,
        "steps": ["learner asks a question", "facilitator authors a reply",
                  "inspect private learner view and staff support evidence",
                  "stop/archive/reset and reject a stale-run request"],
    }


def demonstrate():
    """Use real application methods with synthetic personas and memory-only persistence."""
    store = PortalStore()
    service = PortalService(store, run_id="support-demo-before-reset")
    staff = PortalPrincipal("synthetic-facilitator", "facilitator")
    learner = PortalPrincipal("synthetic-analyst", "soc_analyst")
    try:
        service.start_run(staff)
        question = service.support.request(
            learner, run_id=service.run.run_id, idempotency_key="demo-question",
            objective_id="LO2", message="How should we distinguish a fact from an inference?",
        )
        service.support.respond(
            staff, run_id=service.run.run_id, request_id=question["request_id"],
            idempotency_key="demo-reply", kind="clarification", objective_ids=["LO2"],
            message="A fact is directly supported by an artifact. "
                    "Label an interpretation as inference.",
        )
        view = service.support.view(learner)
        old_run = service.run.run_id
        service.stop_run("Intentionally partial support demonstration", staff)
        reset = service.reset_run(new_run_id="support-demo-after-reset", principal=staff)
        archived = service.review_archive(reset["reset"]["review_archive_id"])
        stale_rejected = False
        try:
            service.support.request(learner, run_id=old_run, idempotency_key="stale-request",
                                    objective_id="LO2", message="Stale browser question")
        except ValueError:
            stale_rejected = True
        return {
            **plan(), "writes_performed": True, "persistence": "memory_only",
            "participant_view": view, "archived_support": archived["report"]["support_requests"],
            "reviewed_objectives": archived["report"]["reviewed_objectives"],
            "aar_status": archived["report"]["status"], "stale_run_rejected": stale_rejected,
            "new_run_request_count": len(service.support.view(learner)["requests"]),
        }
    finally:
        store.close()


def main(argv=None):
    """Explicit execution uses only the local mock runtime and prints synthetic JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(demonstrate() if args.execute else plan(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
