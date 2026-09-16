# Telemetry and Evidence Matrix

## Purpose

This is the authoritative design-time contract between the scenario, attack modules, Splunk content, evaluator guide, and solution guide. A scenario action is not complete until its expected evidence is generated, ingested, searchable, and validated.

The participant guide must not include the answer or the expected evidence values in this document.

## Common event requirements

The authoritative machine-readable definition is the
[NetStrike Exercise Event Contract v1](../event-contract-v1.md). Every
NetStrike-generated event must validate against `schemas/event.v1.json` and
contain:

- `schema_version`: compatible semantic contract version;
- `event_id`: globally unique event identifier;
- `exercise_id`: exercise-definition identifier;
- `run_id`: exercise-session identifier;
- `sequence`: strictly increasing ordering within the run;
- `timestamp`: RFC 3339 UTC timestamp ending in `Z`;
- `event_type`: stable machine-readable event name;
- `source`: producer kind, component, and optional logical host;
- `actor`: account, process, or controller that performed the action;
- `target`: affected identity, host, service, bucket, or file set;
- `action`: attempted operation;
- `outcome`: structured status and optional reason;
- `phase`, plus `checkpoint_id` and `objective_ids` when applicable;
- `attack`: MITRE ATT&CK technique/tactic when applicable;
- `visibility`: participant, facilitator, evaluator, or internal;
- `safety`: simulation, dry-run, allowlist, and non-destructive markers;
- `provenance`: producer/version and optional integrity metadata; and
- `data`: source-specific, recursively redacted details.

`schemas/event.json` is a stable reference to the current versioned schema.
Scenario-control events and defender actions use the same contract; numeric
attack-module phases are not permitted in v1.

## Required evidence

Exact Splunk index and source-type names are provisional until the Cyber Range confirms its conventions.

| Event/activity | Required source and key fields | What a participant should conclude | Evaluator evidence | Generator | Validation |
|---|---|---|---|---|---|
| Fake SSO submission | Web/mock IdP: time, username, landing ID, source IP, user agent, outcome | Sarah interacted with a non-standard authentication page | Event reference plus relation to later identity activity | Phase 2 service | Search by `run_id`, Sarah, and landing ID returns one submission |
| Helpdesk password/MFA reset | Helpdesk audit: ticket ID, caller claim, agent Tyler, requested identity Sarah, verification fields, action time | Reset occurred and callback verification was omitted | Ticket ID and missing-verification field | Phase 3 service | Ticket exists and joins to Sarah and reset event |
| MFA pushes | Mock IdP: factor, device, push count, response, time | Repeated pushes preceded compromise | At least one push artifact in timeline | Phase 4 service | Correct count and order visible |
| Unauthorized factor registration | Mock IdP: `factor-red-01`, actor/session, target user, source IP | Attacker established authentication persistence | Correct factor and registration time | Phase 4/IdP service | Factor state and audit event agree |
| Malicious authentication/session | Mock IdP: `sess-red-01`, Sarah, `203.0.113.77`, result, session creation/revocation | Sarah's identity was used from the exercise threat source | Identity, source, session, and time | IdP service | Login and session events correlate; state verifier can confirm revocation |
| Legitimate baseline authentication | Mock IdP: normal SimCorp source, known endpoint, success | Not every Sarah event is malicious | Correct exclusion or comparison | Baseline generator | At least one believable benign comparison event exists |
| Workstation remote access | Endpoint/controller: Sarah, `FIN-WS01`, process or simulated remote-service event, source | Compromised identity reached the Finance workstation | Affected host and access event | Endpoint adapter | Event appears after session creation and before discovery |
| Process/PowerShell discovery | Windows/Sysmon/adapter: host, user, process, command category, parent, result | Attacker performed account/system discovery | Host, actor, and relevant process evidence | Phase 5 adapter | Expected process and audit events arrive in order |
| Directory enumeration | AD/LDAP audit: bind actor, query category, object counts, DC | Directory discovery expanded the attacker's knowledge | Query evidence and affected directory | Phase 5 module | Query counts are deterministic for baseline data |
| Unauthorized account/group change | AD/controller: `svc-print-sync`, group, initiating actor, result | Persistence or privilege was created on adverse branch | Account/group event and current-state check | Phase 5 adapter | Exists only on adverse branch; reset removes it |
| Failed post-containment login | IdP/AD: account/session, source, failure reason | Containment blocked a subsequent attempt | Failed event after defender action | Scenario engine | Exists on contained branch |
| Mock cloud authentication | `CLOUD01`: key ID, principal `svc-cloud-backup`, source, result | A pre-staged cloud credential was abused | Principal, key, source, and time | Phase 6 service | Auth event joins to later API actions |
| Bucket enumeration | Mock cloud audit: principal, operation, bucket list, result | Actor discovered available mock storage | List operation evidence | Phase 6 service | Expected bucket name is present |
| Bucket-policy change | Mock cloud audit: old/new policy identifier, actor, bucket | Attacker expanded or changed access | Policy-change event and current state | Phase 6 service | Approved policy hash differs before remediation and matches afterward |
| Object access/download | Mock cloud audit: principal, bucket, object or record count, bytes, result | Synthetic customer records were accessed; volume depends on branch | Defensible exposure total | Phase 6 service | Limited branch reports 5 records; adverse branch reports configured full set |
| Blocked bulk cloud access | Mock cloud audit: principal/key, failure reason `revoked` or `denied` | Cloud containment was effective | Failed request after key/policy action | Phase 6 service | Exists only on contained branch |
| Extortion artifact | Controller/portal: message ID, referenced synthetic data, branch | Threat actor claims data theft; claim is not independently proof | Correctly separated claim from confirmed access | Scenario engine | Delivered only on full-exposure branch |
| Impact-task attempt | Controller/endpoint: task ID, host, target directory, result | An impact action was attempted | Attempt time and outcome | Phase 7 safe adapter | Result matches DP4 branch |
| Marker/ransom-note creation | File audit/controller: allowlisted path, file count, hashes | Safe indicators simulate ransomware impact | File set, note, and hashes | Phase 7 safe adapter | No path outside allowlist changes |
| Realized safe impact | Controller/file audit: original/staging paths, count, service status | Disposable business data became unavailable but was not encrypted | Impact scope and service status | Phase 7 safe adapter | Originals exist in controller staging; no VM disk touched |
| Identity containment | IdP audit and current state: session revoked, factor removed, password version changed | Team completed identity containment | Four verifier checks | Participant action/API | State check and audit trail agree |
| Endpoint containment | Isolation controller/host audit: host, actor, state, time | Team isolated the affected endpoint | Isolation and evidence-preservation checks | Participant action | Host cannot use attack path but remains observable to controller |
| AD remediation | AD/current state: account disabled/removed, group membership restored | Unauthorized persistence was removed | State check plus audit event | Participant action | Baseline membership manifest matches |
| Cloud remediation | Mock cloud audit/current state: key revoked, approved policy restored | Team contained cloud access | Key and policy state checks | Participant action/API | Subsequent bulk access is denied |
| Recovery | Backup/controller: manifest, hashes, restored count, health status | Team restored the approved data/service | Passing recovery health check | Participant action | Baseline hashes and service check pass |
| Inject/hint/checkpoint | Controller ledger: MSEL ID, recipient, delivery/ack time, hint level, branch, verifier result | Normally hidden from participants | Complete reconstruction of exercise flow | Scenario engine | Every MSEL row has one final status |

## Splunk views required for the MVP

Only a small amount of supplied content is necessary:

1. **Data health view:** latest event time and count by source for the technical operator.
2. **Identity overview:** authentication, MFA, factor, password-reset, and session activity.
3. **Endpoint/AD overview:** process, remote-access, directory-query, account, and group events.
4. **Mock cloud overview:** authentication, IAM, policy, bucket, and object-access events.
5. **Incident timeline search:** all participant-visible sources correlated by `run_id`, identity, host, IP, and time.

These are starting points, not an answer-revealing attack dashboard. Saved searches shown to participants must not label malicious events directly.

## Evidence-quality rules

- A participant answer must cite an event identifier, timestamp, ticket, file hash, or reproducible search result.
- An alert is a lead, not proof by itself.
- An extortion claim does not prove exfiltration; the cloud audit trail determines confirmed access within the mock.
- Absence of a generated event is not evidence of absence until the technical operator confirms the data source is healthy.
- Evaluators must rate an objective `Not observed`, rather than failed, when missing telemetry makes fair assessment impossible.
