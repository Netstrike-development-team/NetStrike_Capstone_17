# Module 04 — Synthetic MFA and Identity State

This module is a contained exercise service. It must never contact a real
identity provider, tenant, device, phone number, or user.

`identity_actions.py` provides the authoritative mutable identity fixture for
the first blue-team checkpoint. The following containment actions are
registered through the shared safe-action adapter:

- `identity.session.revoke`
- `identity.factor.remove`
- `identity.account.disable`
- `identity.credential.reset`

The state stores only synthetic identifiers and a credential version—not a
password, MFA secret, cookie, or reusable token. Every action is role checked,
run correlated, target allowlisted, idempotent, audited with event contract v1,
and reversible by an exercise-control role.

The Flask service exposes one mutation endpoint: `POST /api/action`. Bearer
tokens are mapped server-side to an actor and role using
`NETSTRIKE_ACTION_TOKENS`; request bodies cannot select their actor, role,
exercise ID, or run ID. The former `/api/push`, `/api/human-approve`, and
`/api/reset` mutation routes return `410 Gone`.

Example token configuration (use runtime-injected test secrets, never commit
the real delivery values):

```bash
export NETSTRIKE_ACTION_TOKENS='{"replace-with-strong-runtime-token":{"actor_id":"scenario-engine","role":"scenario_engine"}}'
export NETSTRIKE_EXERCISE_ID='silent-spider'
export NETSTRIKE_RUN_ID='run-001'
```

The simulator reads `NETSTRIKE_ACTION_API_TOKEN` and submits
`identity.mfa.challenge.record` through this authenticated boundary.

Run the integration tests from the repository root:

```bash
pytest modules/04-mfa-fatigue-sim/tests -v
```
