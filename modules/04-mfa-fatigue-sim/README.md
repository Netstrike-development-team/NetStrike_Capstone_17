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

The older Flask demonstration routes in `mock_okta_api.py` are retained only as
prototype UI behavior. They are not an authorized exercise-control interface
and must not be exposed in a delivery environment until they submit requests
through the safe-action adapter and server-side authentication is present.

Run the integration tests from the repository root:

```bash
pytest modules/04-mfa-fatigue-sim/tests -v
```
