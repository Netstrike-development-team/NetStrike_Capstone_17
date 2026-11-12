# Synthetic profile initialization v1 (#46)

## Maintained input

The exercise runtime consumes a local JSON bundle containing exactly
`schema_version`, `seed`, and `profiles`. Version `1.0.0` profiles validate
against `schemas/target_profile.v1.json`. The committed input is
`orchestrator/fixtures/identity-profiles.v1.json`, built from the existing
reviewed SimCorp employee fixture using the OSINT identity and email extractors.
No live source is queried. There is no new paid or external runtime dependency;
JSON Schema validation uses the existing shared `jsonschema` dependency.

The legacy profiler and `schemas/target_profile.json` remain unchanged.
Their `.com` profiles are **not** maintained exercise input and will fail the
new startup boundary. Arbitrary imported profiles are never silently rewritten
or treated as approved because they say `synthetic=true`.

## Export and configure

From the repository root:

```bash
python -m modules.01-osint-profiler.exercise_profiles \
  --seed silent-spider-profiles-v1 --output /tmp/simcorp-profiles.json
```

The default runtime uses the committed fixture. To load a reviewed replacement,
set `NETSTRIKE_PROFILE_FIXTURE` to its local path before starting the dashboard.
The fixture seed must match `participant_experience.profiles.seed` in the
scenario definition. The scenario also binds `identity_employee_id` and
`helpdesk_employee_id`; the default bindings are Sarah (`emp_001`) and Tyler
(`emp_005`), with James resolved as Sarah's manager.

The current identity slice is intentionally bound to Sarah and its configured
SSO/MFA identity. Rebinding an exercise actor requires reviewing the associated
storyline/injects, not merely changing a profile field. This feature does not
create additional login accounts, authentication sessions, AD privileges, or
new response targets for the other directory entries.

Copy the matching project source as well as the wheel bundle to the range.
Source must include the shared validator, versioned schema, profile fixture,
and module 01's reviewed roster and extractors. The Python wheel bundle alone
does not contain these project files.

## Validation and confidence

Startup fails before any run evidence is emitted when the fixture is missing,
malformed, oversized, empty, duplicated, unsupported, or unsafe. Errors identify
the profile index/field without echoing submitted personal/contact data.

- Only employees matching the reviewed local roster are accepted; names,
  title, department, manager, and role mapping must agree.
- Every profile declares the schema version and synthetic marker. Seeded
  UUIDs, employee bindings, and source identifiers are validated.
- Account names are **configured** in `simcorp.test`, not discovered accounts.
- Email candidates use only the allowlisted namespace and reviewed name
  patterns. They remain **inferred**, including the first/best guess; a guessed
  pattern is not promoted to an explicit observed address.
- Optional missing contacts are **unknown** and are not fabricated. No personal
  phone numbers are imported; the only permitted optional number is the
  explicitly configured synthetic helpdesk contact.
- External URLs, public-domain contacts, unknown personal-data fields, secret
  fields, invalid ranks, duplicate contacts, and unreviewed identities are denied.

The same fixture/seed produces the same normalized directory, profile IDs,
bindings, and catalog SHA256, regardless of input order. Connector scrape UUIDs
and wall-clock timestamps are not used as identity seeds. Runtime audit event
UUIDs and timestamps remain run-specific.

## Runtime and evidence

Validated Sarah metadata seeds the existing mock identity baseline. Prepare
emits a facilitator-only `scenario.profiles.initialized` event containing the
catalog fingerprint/count and bound context. Pre-exercise fake-SSO and helpdesk
evidence includes profile references and confidence labels; profile IDs join
identity and helpdesk records within the normal exercise/run event contract.
The missing callback-verification evidence and existing checkpoint rules are
unchanged. A directory lookup alone is not evidence of compromise.

`GET /api/participant/directory` is authenticated, participant-role-only, and
read-only. The participant console's **SimCorp staff directory** displays all
20 reviewed employees without target rankings, scenario bindings, branch
answers, or controls. Facilitators can inspect **Profile readiness** and
`profile_initialization` in their authenticated state response. Inferred email
confidence is retained in directory and generated evidence.

Reset restores the pinned, already-validated baseline. It does not reload an
edited fixture mid-run. A fresh runtime performs validation again. Profile,
SSO, and MFA baseline verification are reported together; VM snapshots remain
the infrastructure reset mechanism.

## Handoff and remaining acceptance

Dev owns the input contract, export, startup binding, directory/API controls,
canonical evidence, and regression tests. Patrick can ingest the new
`scenario.profiles.initialized` record as facilitator-only setup evidence and
verify helpdesk/profile correlation under #102. Live Splunk verification is
not claimed by this change. Anna owns reviewing the wording and directory
experience during participant rehearsal; Ashley coordinates that rehearsal.

Local verification command:

```bash
pytest shared/tests orchestrator/tests dashboard/tests \
  modules/01-osint-profiler/tests modules/04-mfa-fatigue-sim/tests \
  modules/05-lateral-movement/tests scripts/tests -q
```

Tests cover deterministic export, partial/empty/invalid input, approved-roster
and contact boundaries, no-network export, identity/helpdesk binding, copied
read-only views, confidence in canonical events, pinned reset, and participant
role separation. API/static checks do not replace browser visual rehearsal or
live Cyber Range ingestion/readiness validation.
