"""Run-scoped human support API operations over append-only canonical events."""

from orchestrator.controller import ControllerError
from orchestrator.support import (
    COMPONENT, KINDS, LEARNER_ROLES, MAX_ACTOR_REQUESTS, MAX_REQUESTS,
    OBJECTIVE_IDS, REQUEST, RESPONSE, STAFF_ROLES, objectives, participant_records,
    support_index, text,
)
from shared.events import EventBuilder, EventContext, entity


class SupportEvidenceError(ControllerError):
    """Audit/acknowledgement failure: a write may have committed before the error."""


class SupportWorkflow:
    """Communication only: never execute remediation, choose branches or grade."""

    def __init__(self, service):
        self.service = service

    def _events(self):
        run = self.service.run
        return self.service.store.events(run.definition.exercise_id, run.run_id)

    def _scope(self, principal, run_id, roles):
        if principal.role not in roles:
            raise ControllerError("role cannot perform this support operation")
        if run_id != self.service.run.run_id:
            raise ValueError("run changed; refresh before requesting or replying")

    def view(self, principal, *, staff=False):
        """Read a consistent, current-run queue without mutation or hidden answers."""
        with self.service.run.state_lock:
            self._scope(principal, self.service.run.run_id,
                        STAFF_ROLES if staff else LEARNER_ROLES)
            records = support_index(self._events())
            return {
                "run_id": self.service.run.run_id,
                "run_state": self.service.run.controller.state.value,
                "principal_role": principal.role,
                "requests": records if staff else participant_records(records, principal.actor_id),
                "automatic_answers": False, "ratings_require_evaluator": True,
            }

    def _retry_request(self, events, principal, key, expected):
        for event in events:
            if (event["event_type"] == REQUEST and event["actor"]["id"] == principal.actor_id
                    and event["data"]["request_key"] == key):
                actual = {field: event["data"][field] for field in expected}
                if actual != expected or event["objective_ids"] != [expected["objective_id"]]:
                    raise ValueError("support retry key conflicts with a previous payload")
                return self._receipt(event, replayed=True)
        return None

    @staticmethod
    def _receipt(event, *, replayed=False):
        return {
            "run_id": event["run_id"], "event_id": event["event_id"],
            "request_id": (event["event_id"] if event["event_type"] == REQUEST
                           else event["data"]["request_id"]),
            "status": "requested" if event["event_type"] == REQUEST else "answered",
            "replayed": replayed,
        }

    def _append(self, principal, event_type, data, scope_ids, events):
        run = self.service.run
        if ([event["sequence"] for event in events] != list(range(1, len(events) + 1))
                or run.sequencer.sequence != len(events)):
            raise ControllerError("support audit ledger inconsistent; preserve evidence")
        request = event_type == REQUEST
        actor_type = "participant" if request else "facilitator"
        builder = EventBuilder(
            EventContext(run.definition.exercise_id, run.run_id, actor_type, COMPONENT, "1.0.0"),
            sequence_factory=run.sequencer.next,
        )
        try:
            event = builder.build(
                event_type=event_type, phase="control",
                actor=entity(actor_type, principal.actor_id, role=principal.role),
                action="exercise.support.request" if request else "exercise.support.respond",
                target=entity("support_queue", run.run_id) if request else entity(
                    "support_request", data["request_id"]),
                outcome_status="success", visibility="facilitator", dry_run=False,
                message="Participant help requested" if request else "Exercise staff reply recorded",
                objective_ids=scope_ids, correlation_ids=() if request else (data["request_id"],),
                safety_controls=("human-authored", "run-scoped", "append-only", "no-auto-grading"),
                data={**data, "elapsed_seconds": run.controller.elapsed_seconds,
                      "run_state": run.controller.state.value},
            )
            self.service.store.append_event(event)
        # This safety boundary includes construction errors after sequence allocation.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Never issue an unaudited answer/receipt or rewind a possibly written event.
            try:
                run.fail_safe_stop(
                    "support evidence persistence unavailable",
                    operator=entity("system", "exercise-support", role="technical_operator"),
                )
            except ControllerError:  # Other latches were attempted despite partial audit failure.
                raise SupportEvidenceError(
                    "support evidence unavailable; safety audit incomplete; preserve evidence"
                ) from exc
            raise SupportEvidenceError(
                "support evidence unavailable; preserve evidence before reset"
            ) from exc
        return self._receipt(event)

    def request(self, principal, *, run_id, idempotency_key, objective_id, message):
        """Persist one participant question with bounded, idempotent retries."""
        with self.service.run.state_lock:
            self._scope(principal, run_id, LEARNER_ROLES)
            message = text(message, "question")
            key = text(idempotency_key, "retry key", 128)
            if objective_id not in OBJECTIVE_IDS:
                raise ValueError("invalid support objective")
            events = self._events()
            records = support_index(events)
            expected = {"request_key": key, "objective_id": objective_id, "text": message}
            retry = self._retry_request(events, principal, key, expected)
            if retry:
                return retry
            if self.service.run.controller.state.value not in {"running", "paused"}:
                raise ControllerError("new help requests require running or paused play")
            own = [record for record in records if record["requester_id"] == principal.actor_id]
            if any(record["response"] is None for record in own):
                raise ValueError("one pending request per participant; await the staff reply")
            if len(own) >= MAX_ACTOR_REQUESTS or len(records) >= MAX_REQUESTS:
                raise ValueError("support request limit reached")
            return self._append(principal, REQUEST, expected, (objective_id,), events)

    def respond(self, principal, *, run_id, request_id, idempotency_key,
                kind, message, objective_ids):
        """Only authorized humans reply; technical staff can report platform issues."""
        # Explicit run/actor/payload boundaries are intentionally not a free-form option map.
        # pylint: disable=too-many-arguments,too-many-locals
        with self.service.run.state_lock:
            self._scope(principal, run_id, {"facilitator", "technical_operator"})
            if kind not in KINDS:
                raise ValueError("invalid support reply kind")
            if principal.role == "technical_operator" and kind != "platform_issue":
                raise ControllerError(
                    "technical operators can report platform issues, not coaching"
                )
            message = text(message, "reply")
            request_id = text(request_id, "request id", 128)
            key = text(idempotency_key, "retry key", 128)
            scope_ids = objectives(objective_ids)
            events = self._events()
            records = support_index(events)
            expected = {
                "request_id": request_id, "response_key": key, "kind": kind, "text": message,
            }
            retry = self._retry_response(events, principal, key, expected, scope_ids)
            if retry:
                return retry
            state = self.service.run.controller.state.value
            if (state not in {"running", "paused", "stopped"}
                    or state == "stopped" and kind != "platform_issue"):
                raise ControllerError(
                    "reply requires live play or a stopped-run platform explanation"
                )
            record = next((record for record in records
                           if record["request_id"] == request_id), None)
            if record is None:
                raise ValueError("request does not belong to the current run")
            if record["response"] is not None:
                raise ValueError("request already answered; replies are immutable")
            return self._append(principal, RESPONSE, expected, scope_ids, events)

    def _retry_response(self, events, principal, key, expected, scope_ids):
        for event in events:
            if (event["event_type"] == RESPONSE and event["actor"]["id"] == principal.actor_id
                    and event["data"]["response_key"] == key):
                if ({field: event["data"][field] for field in expected} != expected
                        or event["objective_ids"] != scope_ids):
                    raise ValueError("support retry key conflicts with a previous payload")
                return self._receipt(event, replayed=True)
        return None
