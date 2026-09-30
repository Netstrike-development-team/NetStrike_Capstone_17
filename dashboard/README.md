# Participant and facilitator portal API

This FastAPI service exposes the identity vertical slice without trusting actor, role, run, or exercise identifiers supplied by a browser.

- Participant endpoints show only participant-visible injects, accept allowlisted safe actions, and score the DP1 submission.
- Facilitator endpoints prepare, start, pause, resume, advance, manually deliver or skip an item, resolve DP2 from authoritative state, emergency-stop, reset, and inspect the full run.
- Bearer tokens and roles come from `NETSTRIKE_PORTAL_TOKENS`; there are no built-in credentials.
- SQLite persists validated events, submissions, and a queryable identity timeline. Identity capture stores only a keyed one-way reference to a submitted synthetic credential; raw passwords, cookies, MFA codes, and tokens are never written.
- Facilitators can download canonical JSONL or a flattened CSV view for evaluation and downstream ingestion.
- Interactive API documentation is disabled so participant users cannot discover facilitator routes from the service itself.
- `/participant` and `/facilitator` provide responsive, dependency-free browser consoles. Participant actions require users to enter evidence-supported target IDs; the HTML does not reveal the scenario answer identifiers.

Example offline configuration:

```bash
export NETSTRIKE_PORTAL_TOKENS='{
  "replace-with-24-plus-random-characters-a": {"actor_id": "fac-01", "role": "facilitator"},
  "replace-with-24-plus-random-characters-b": {"actor_id": "learner-01", "role": "identity_responder"},
  "replace-with-24-plus-random-characters-c": {"actor_id": "simcorp-sso", "role": "identity_capture_service"}
}'
export NETSTRIKE_IDENTITY_AUDIT_KEY='replace-with-32-plus-random-bytes'
python -m uvicorn dashboard.app:create_default_app --factory --host 0.0.0.0 --port 8080
```

Tokens are injected on `CTRL01`; they must not be committed, logged, or included in exported evidence.
The audit key is also injected at runtime and must remain stable for the duration of a run.

## Synthetic identity capture

Only a token configured with the `identity_capture_service` role may call
`POST /api/services/identity/interactions`. The authenticated token owns the
source-service identity; a caller cannot select it in the request body. The
service accepts a bounded JSON object containing:

- `phase`, `synthetic_identity`, `action`, `result`, and `source_event_id`;
- an optional RFC 3339 `occurred_at`; and
- optional paired `credential_kind` and `synthetic_credential` fields.

The raw `synthetic_credential` exists only long enough to calculate an
HMAC-SHA256 run-scoped reference. The stored record and canonical
`identity.interaction.recorded` event contain the reference, correlation
fields, result, and provenance, but never the submitted value. Canonical events
automatically appear in the existing facilitator JSONL and CSV exports for
Splunk or after-action review. Facilitators can query the ordered current-run
timeline at `GET /api/facilitator/identity-audit`.

Reset removes the completed run's transient identity-audit projection and
verifies it is empty before reporting success. The normalized event remains in
the exercise evidence stream so it can be exported before VM snapshot restore.
