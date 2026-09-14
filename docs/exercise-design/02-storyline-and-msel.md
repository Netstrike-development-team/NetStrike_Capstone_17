# Storyline, Decision Branches, and MSEL

## Exercise narrative

SimCorp is a fictitious services company preparing its quarterly customer billing export. On Monday morning, Finance Vice President Sarah Mitchell reports unexpected MFA prompts. A helpdesk ticket from the previous evening records an urgent password and MFA reset request supposedly made by Sarah while travelling.

Before exercise play, a threat actor used public SimCorp information to create a credible pretext, directed Sarah to a fake SimCorp SSO page, and impersonated her during a call to helpdesk technician Tyler Brennan. The reset allowed the actor to establish a session and register an unauthorized factor. The actor then accessed a Finance workstation, searched internal information, enumerated Active Directory, obtained a pre-staged mock-cloud credential, and prepared to retrieve synthetic customer data.

Participants enter while the compromise is still developing. They must determine what happened and act. At fixed checkpoints, the controller verifies defensive state. The engine then runs one of two safe variants for the next stage. Successful defenses reduce impact; late or incomplete actions allow additional simulated attacker progress. All paths reach the recovery and debrief objectives.

## Logical assets

The exact VM mapping is agreed with the Cyber Range, but the story requires these logical assets:

| Asset | Function |
|---|---|
| `IDP01` | SimCorp SSO/MFA mock and administration interface |
| `HELPDESK01` | Simulated helpdesk tickets and verification audit trail |
| `FIN-WS01` | Sarah Mitchell's designated Finance workstation |
| `DC01` | SimCorp Active Directory service or controlled directory simulation |
| `CLOUD01` | Python mock IAM/S3 service containing synthetic customer exports |
| `FILE01` | Disposable exercise data and known-good backup used for safe impact/recovery |
| `SPLUNK01` | Cyber Range-provided Splunk instance |
| `CTRL01` | Scenario engine, event ledger, participant portal, and action adapters |

Multiple logical services may share a VM for the MVP. The controller and Splunk must remain outside participant administrative control.

## Known truth — evaluator only

The canonical answer is:

1. Public SimCorp sources exposed Sarah's role, management chain, email pattern, SSO provider, and helpdesk contact information.
2. Sarah submitted fictitious credentials to the isolated fake SSO page.
3. The actor called Tyler while impersonating Sarah. Tyler performed a password/MFA reset without completing the required callback verification.
4. The actor authenticated as Sarah from reserved exercise source `203.0.113.77`, registered factor `factor-red-01`, and created session `sess-red-01`.
5. The actor used the session to access `FIN-WS01` through the simulated remote-access path.
6. Directory discovery identified privileged and service accounts. On the adverse branch, the actor adds `svc-print-sync` to a privileged exercise group.
7. A pre-staged mock-cloud key for `svc-cloud-backup` is used to access `simcorp-customer-exports`.
8. On the adverse cloud branch, all synthetic records are retrieved; on the contained branch, only a small sample is accessed.
9. A pre-staged impact task attempts to make disposable files unavailable and writes a ransom note. It does not encrypt real data or VM disks.

## Decision branches

Branches are deliberately limited to four checkpoints. Each check uses environment state, not facilitator opinion. When a verifier is unavailable, the facilitator uses the documented manual fallback and records the reason.

### DP1 — Incident classification

**Pass condition:** Team identifies Sarah Mitchell, likely identity compromise, and three relevant artifacts by exercise minute 40.

- **Pass:** Manager inject acknowledges escalation; no hint is issued.
- **Miss:** Manager asks whether the team has correlated the helpdesk and identity records. This is a level-one hint and is recorded.

DP1 does not change attacker capability; it only controls support and scoring.

### DP2 — Identity and endpoint containment

**Pass condition:** `sess-red-01` revoked, `factor-red-01` removed, Sarah's exercise password reset, and `FIN-WS01` remote path isolated by minute 85.

- **Pass — contained variant:** A new authentication attempt fails. The attacker continues using a pre-staged mock-cloud key already obtained before containment; this ensures later objectives remain available.
- **Miss — adverse variant:** The session remains valid long enough to create `svc-print-sync`, add it to the designated privileged exercise group, and perform further directory discovery.

### DP3 — Cloud containment

**Pass condition:** Team identifies `svc-cloud-backup`, revokes the unauthorized key, and restores the approved bucket policy by minute 135.

- **Pass — limited exposure:** The engine records access to five synthetic records and a blocked bulk-download attempt.
- **Miss — full exposure:** The engine records download of the full synthetic data set and generates an extortion-message inject.

### DP4 — Impact and recovery

**Pass condition before impact:** Designated persistence removed, affected host isolated, and impact task disabled by minute 150.

- **Pass — blocked impact:** The simulated impact attempt is blocked; five canary files receive harmless marker companions for investigation.
- **Miss — realized impact:** All disposable files under the allowlisted exercise directory are moved to an unavailable staging directory and marker files plus a ransom note are created. Originals remain recoverable by the controller.

All teams then complete recovery validation and the final brief.

## Master Scenario Events List

Times are relative to the start of exercise play, after the briefing. The facilitator may shift an event by up to ten minutes to maintain learning value. Any larger change is recorded as an exercise deviation.

| ID | Time/trigger | Type and delivery | Event or inject | Expected participant action | Control/evaluation note |
|---|---:|---|---|---|---|
| PRE-01 | Before play | Setup | Load baseline identities, tickets, disposable files, mock-cloud objects, expected telemetry, and known-good backup. | None | Health and baseline checks must pass. |
| PRE-02 | T-35 to T-5 | Automated history | Generate fake SSO submission, helpdesk reset, MFA factor registration, malicious login, session creation, and initial workstation access. | None | Events are backdated relative to play and tagged with `run_id`. |
| MSEL-01 | 00:00 | Portal/email inject | Sarah reports repeated MFA prompts and asks whether IT is performing maintenance. | Acknowledge, open an incident record, establish severity and scope. | Starts LO1 clock. |
| MSEL-02 | 00:05 | Portal ticket | Provide the previous evening's urgent helpdesk reset ticket, including the missing callback-verification field. | Correlate caller claim, ticket timing, identity changes, and policy failure. | Do not explain that the ticket is malicious. |
| ACT-01 | 00:15 | Automated attacker action | Use `sess-red-01` for a second simulated authentication and access to `FIN-WS01`. | Find the source, user, session, and affected host in Splunk. | Creates live evidence after exercise start. |
| MSEL-03 | 00:25 | Phone/portal inject | Tyler states that the caller knew Sarah's manager and travel story, so he completed the reset. | Interview the simulated witness; record what is fact versus recollection. | Facilitator follows scripted answers only. |
| DP1 | 00:40 | Checkpoint | Evaluate incident classification and submitted evidence. | Submit triage answer if not already submitted. | Issue the documented hint on miss. |
| MSEL-04 | 00:45 | Portal inject | Rebecca Nwosu requests a five-minute status: affected identity, confidence, immediate risk, and next action. | Provide a concise, evidence-based update. | Evaluates communication without revealing the answer. |
| ACT-02 | 00:50 | Automated attacker action | Run safe process and directory discovery on the designated endpoint. | Detect execution, identify account/host, preserve evidence, and begin containment. | Command output and process events must reach Splunk. |
| ACT-03 | 01:05 | Automated attacker action | Attempt persistence through the designated exercise account/group change. | Review directory audit events and reverse unauthorized changes. | Action variant depends on verified identity state where practical. |
| MSEL-05 | 01:15 | Portal inject | Helpdesk supervisor asks whether Sarah's access can be restored immediately for payroll approval. | Balance business need with containment; explain conditions for safe restoration. | There is no penalty for keeping the account restricted with rationale. |
| DP2 | 01:25 | Checkpoint | Verify session, factor, password, endpoint isolation, evidence preservation, and unauthorized group state. | Complete containment and validate it. | Select contained or adverse branch; record verifier results. |
| ACT-04A | DP2 pass | Automated branch | Reject a new authentication and record blocked directory access. | Confirm containment effectiveness and continue scoping. | Do not end the exercise. |
| ACT-04B | DP2 miss | Automated branch | Create/use `svc-print-sync`, add the exercise privilege, and enumerate additional directory objects. | Identify the new persistence and remediate it. | Safe, pre-defined account only. |
| ACT-05 | 01:35 | Automated attacker action | Authenticate to `CLOUD01` as `svc-cloud-backup`, list buckets, and retrieve a small object. | Identify principal, key, source, bucket, and likely access path. | Cloud is explicitly labelled as a Python mock in staff material. |
| MSEL-06 | 01:45 | Portal/chat inject | Finance reports an unexpected delay in the customer export job. | Relate business symptom to technical evidence; avoid assuming ransomware. | Tests impact assessment. |
| ACT-06 | 01:55 | Automated attacker action | Change mock bucket policy and begin staged synthetic-record access. | Estimate data scope, revoke key/principal, and restore policy. | No real cloud or personal data. |
| MSEL-07 | 02:05 | Portal inject | Legal asks what data is confirmed accessed and whether exfiltration is proven. | Distinguish access, download, and inferred external transfer. | Evaluates evidence discipline. |
| DP3 | 02:15 | Checkpoint | Verify cloud identity, key state, bucket policy, and exposure estimate. | Submit cloud assessment and finish containment. | Select limited- or full-exposure branch. |
| ACT-07A | DP3 pass | Automated branch | Block bulk access after five synthetic records; log failed retrievals. | Verify the control and document residual risk. | Limited-exposure answer key applies. |
| ACT-07B | DP3 miss | Automated branch | Record full synthetic data retrieval and generate extortion artifact. | Contain remaining access and update incident impact. | No data leaves the lab. |
| MSEL-08 | 02:20 | Portal/email inject | Deliver either a blocked-access notification or an extortion message referencing the synthetic data. | Update severity, stakeholders, and response priorities. | Branch-specific inject. |
| DP4 | 02:30 | Checkpoint | Verify endpoint isolation, persistence removal, and impact-task state. | Disable the designated impact path and validate. | Select blocked- or realized-impact variant. |
| ACT-08A | DP4 pass | Automated branch | Log blocked impact; create marker companions for five canary files. | Inspect artifacts and confirm production-like data remains available. | Marker files only. |
| ACT-08B | DP4 miss | Automated branch | Move disposable files to controller-managed staging, create markers, and write a ransom note. | Contain, preserve artifacts, and invoke the recovery procedure. | No encryption and no VM-disk interaction. |
| MSEL-09 | 02:40 | Portal inject | Executive asks whether critical service can be restored and what remains unknown. | Restore designated data/service and communicate constraints. | Starts final recovery/report window. |
| END-01 | 02:50 | Exercise end | Freeze scoring, preserve run ledger, and collect final incident brief. | Submit final report and stop technical actions. | Proceed directly to 30-minute hotwash. |

## Facilitator pacing rules

- Pause the exercise for a platform fault, safety concern, or missing required telemetry.
- Do not pause merely because the team is making an incorrect decision.
- A level-one hint points to a data source; a level-two hint suggests a search concept; a level-three intervention states the required next action.
- Never improvise a new technical attacker action during the MVP. Use only an allowlisted MSEL action.
- If a branch action fails technically, deliver its pre-generated evidence bundle, mark the action as simulated fallback, and continue.
