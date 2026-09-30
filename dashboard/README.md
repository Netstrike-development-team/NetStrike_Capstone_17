# Participant and facilitator portal API

This FastAPI service exposes the identity vertical slice without trusting actor, role, run, or exercise identifiers supplied by a browser.

- Participant endpoints show only participant-visible injects, accept allowlisted safe actions, and score the DP1 submission.
- Facilitator endpoints prepare, start, pause, resume, advance, manually deliver or skip an item, resolve DP2 from authoritative state, emergency-stop, reset, and inspect the full run.
- Bearer tokens and roles come from `NETSTRIKE_PORTAL_TOKENS`; there are no built-in credentials.
- SQLite persists validated events and submissions. Run IDs isolate old and new exercise data without deleting the prior run.
- Facilitators can download canonical JSONL or a flattened CSV view for evaluation and downstream ingestion.
- Interactive API documentation is disabled so participant users cannot discover facilitator routes from the service itself.
- `/participant` and `/facilitator` provide responsive, dependency-free browser consoles. Participant actions require users to enter evidence-supported target IDs; the HTML does not reveal the scenario answer identifiers.

Example offline configuration:

```bash
export NETSTRIKE_PORTAL_TOKENS='{
  "replace-with-24-plus-random-characters-a": {"actor_id": "fac-01", "role": "facilitator"},
  "replace-with-24-plus-random-characters-b": {"actor_id": "learner-01", "role": "identity_responder"}
}'
python -m uvicorn dashboard.app:create_default_app --factory --host 0.0.0.0 --port 8080
```

Tokens are injected on `CTRL01`; they must not be committed, logged, or included in exported evidence.
