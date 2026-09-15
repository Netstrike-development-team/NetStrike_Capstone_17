# CITEF Requirements and Exercise Approval Pack

**Gate:** M1 — Design approval (Weeks 1–2)

**Tracking issue:** [#76](https://github.com/Netstrike-development-team/NetStrike_Capstone_17/issues/76)

**Target decision date:** September 28, 2026

**Status:** Proposed decisions are ready for team and CITEF review. External confirmations and named sign-off are pending.

## Purpose

This document is the working record for approving Operation Silent Spider and
confirming the Cyber Range resources on which it will run. It is designed to be
completed during one requirements meeting, followed by a short team decision
review.

Unknown answers do not prevent prototyping, but issue #76 cannot close until:

1. the team accepts or changes every proposed exercise decision;
2. a named CITEF contact confirms the available environment and constraints;
3. every unavailable dependency has an accepted zero-cost fallback or scope
   reduction; and
4. resulting changes are reflected in the design package and backlog.

## Approval workflow

| Step | Owner | Output | Exit condition |
|---|---|---|---|
| 1. Team review | Student team | Accepted or amended exercise decisions | No unresolved disagreement on MVP purpose or learning objectives |
| 2. CITEF requirements session | Team lead and CITEF contact | Completed environment questionnaire | Every required field has an answer, owner, or answer-by date |
| 3. Feasibility review | Technical lead | Confirmed topology and fallback choices | MVP can be delivered without paid student resources |
| 4. Baseline update | Document owners | Updated design documents and issues | Decisions, assumptions, and estimates agree |
| 5. Sign-off | Team representative and CITEF contact | Approval record in this document | Both parties approve or record explicit exceptions |

## Proposed exercise decisions

The following are the baseline recommendations from the design package. Mark
each row `Approved`, `Approved with change`, or `Not approved`, and record the
decision owner. A blank row means the decision remains pending.

| Decision | Proposed baseline | Status | Owner/date | Change or rationale |
|---|---|---|---|---|
| Audience | Post-secondary learners, co-op students, and junior SOC/IR practitioners | Pending | — | — |
| Prerequisite skill | Basic networking, authentication, AD, command line, incident response, and introductory Splunk | Pending | — | — |
| Team size | Ideal 4; supported 2–6 | Pending | — | — |
| Duration | 20-minute briefing, 2h50 play, 30-minute hotwash; 3h40 total | Pending | — | — |
| Delivery model | One participant team in one isolated CITEF instance | Pending | — | — |
| Exercise perspective | Blue-team-only MVP beginning after identity compromise | Pending | — | — |
| Learning objectives | Five objectives: triage, timeline, identity/endpoint containment, mock-cloud containment, recovery/communication | Pending | — | — |
| Decision model | Four deterministic checkpoints with contained/adverse variants | Pending | — | — |
| Simulation control | MSEL-driven automation with manual facilitator fallback | Pending | — | — |
| SIEM | CITEF-provided Splunk; the project supplies sources, field mappings, searches, and dashboards | Pending | — | — |
| Cloud | Stateful Python mock only; no public-cloud account | Pending | — | — |
| Impact | Marker/move simulation on disposable fixtures; no encryption | Pending | — | — |
| Reset target | Validated baseline restored within 20 minutes | Pending | — | — |
| Deferred work | Learner-operated red team, open-ended attacker, CALDERA dependency, GHOSTS, public cloud, multi-tenancy, custom SIEM | Pending | — | — |

### Learning-objective approval

The detailed measures are in
[01-exercise-charter.md](01-exercise-charter.md#learning-objectives). Approval
means the objectives are appropriate for the audience, observable using the
confirmed environment, and achievable in the available play time.

| Objective | Approved? | Required change | Approver/date |
|---|---|---|---|
| LO1 — Triage the identity incident | Pending | — | — |
| LO2 — Reconstruct the intrusion | Pending | — | — |
| LO3 — Contain identity and endpoint access | Pending | — | — |
| LO4 — Determine and contain mock-cloud exposure | Pending | — | — |
| LO5 — Recover and communicate | Pending | — | — |

## CITEF environment questionnaire

### Contacts, access, and delivery

| Question | CITEF answer | Owner or source | Confirm by |
|---|---|---|---|
| Who is the primary technical contact and delivery-day escalation contact? | Pending | — | — |
| Who owns VM creation, snapshots, restoration, and deletion? | Pending | — | — |
| How will students access CITEF during development and exercise delivery? | Pending | — | — |
| What approval is required before deploying services, agents, or Ansible changes? | Pending | — | — |
| Are participant accounts persistent or created per event? | Pending | — | — |
| What dates are available for the first deployment, rehearsal, and final exercise? | Pending | — | — |
| How much lead time does CITEF require for topology or software changes? | Pending | — | — |

### Compute and logical-asset mapping

The MVP needs the logical assets below, but Linux services may share a VM. The
minimum practical layout keeps the domain controller, learner workstation, and
Splunk separate while consolidating project-owned services.

| Logical asset | Preferred placement | Can consolidate with | Confirmed CITEF mapping/specification |
|---|---|---|---|
| `CTRL01` | Linux VM controlled by exercise staff | `IDP01`, `HELPDESK01`, `CLOUD01`, `FILE01` | Pending |
| `IDP01` | Project service | `CTRL01` | Pending |
| `HELPDESK01` | Project service | `CTRL01` | Pending |
| `CLOUD01` | Stateful Python mock | `CTRL01` | Pending |
| `FILE01` | Disposable fixture storage | `CTRL01` or `FIN-WS01` | Pending |
| `DC01` | Separate Windows Server VM | None preferred | Pending |
| `FIN-WS01` | Separate Windows workstation VM | None preferred | Pending |
| `SPLUNK01` | CITEF-managed Splunk VM | None preferred | Pending |

Confirm for every supplied VM:

- operating system and version;
- vCPU, RAM, and available disk;
- administrative-access model;
- supported snapshot/image mechanism;
- hostname/IP persistence across reset; and
- whether nested virtualization or containers are permitted.

### Network, DNS, and time

| Requirement | CITEF answer | Evidence/owner |
|---|---|---|
| Exercise subnet and address allocation | Pending | — |
| Internet-egress policy and enforcement point | Pending | — |
| Management paths that remain reachable during endpoint isolation | Pending | — |
| DNS service and approved internal exercise domain | Pending | — |
| Firewall changes the project may request or automate | Pending | — |
| NTP/time source for Windows, Linux, controller, and Splunk | Pending | — |
| Maximum expected clock skew | Pending | — |
| Reserved address to represent the fictitious threat source | `203.0.113.77` proposed | — |

The exercise requires Internet egress to be denied by default during delivery.
Any development-time package access must be a separately approved management
path and must not be reachable by participants or simulation modules.

### Splunk

| Question | CITEF answer | Evidence/owner |
|---|---|---|
| Splunk product, edition, and exact version | Pending | — |
| License constraints during development and delivery | Pending | — |
| VM owner and Splunk administrator | Pending | — |
| Allowed ingestion methods: HEC, Universal Forwarder, syslog, file monitor | Pending | — |
| Available indexes and whether a dedicated index is permitted | Pending | — |
| Required naming convention for index, source, sourcetype, and host | Pending | — |
| Installed or permitted add-ons, especially Windows/Sysmon | Pending | — |
| Data retention and cleanup policy | Pending | — |
| Participant role/search permissions and export limits | Pending | — |
| Facilitator-only index or role separation | Pending | — |
| Saved-search/dashboard deployment process | Pending | — |
| Ingestion latency target and health-monitoring method | Pending | — |
| Whether previous-run data may remain if isolated by `run_id` | Pending | — |

The project will not build a competing SIEM. It will provide normalized event
producers, Splunk field mappings, health queries, learner views, solution-guide
searches, and export validation.

### Windows, Active Directory, and endpoint telemetry

| Question | CITEF answer | Evidence/owner |
|---|---|---|
| Windows Server and workstation versions | Pending | — |
| Domain/forest name and ability to seed fictitious accounts/groups | Pending | — |
| Participant permissions for approved account/group actions | Pending | — |
| Available Windows event channels and audit policy | Pending | — |
| Sysmon availability and approved configuration | Pending | — |
| Endpoint isolation mechanism that preserves controller visibility | Pending | — |
| Whether the project may schedule safe PowerShell/Ansible tasks | Pending | — |
| Snapshot/reset behavior for AD and endpoint state | Pending | — |

### Automation, deployment, and secrets

| Question | CITEF answer | Evidence/owner |
|---|---|---|
| Approved Ansible control host and connection method | Pending | — |
| Allowed automation protocols and ports | Pending | — |
| Runtime secret-injection method | Pending | — |
| Offline package or artifact-transfer mechanism | Pending | — |
| Container runtime availability, if any | Pending | — |
| Source/artifact review required before installation | Pending | — |
| Location for exported run evidence and retention period | Pending | — |

### Safety, stop, and reset ownership

| Requirement | CITEF answer | Evidence/owner |
|---|---|---|
| Approved target/identity/path allowlist owner | Pending | — |
| Emergency-stop operator and communication channel | Pending | — |
| Hypervisor/snapshot controls remain outside participant access | Required | — |
| Snapshot restore target time | Pending | — |
| Maximum total reset window | 20 minutes proposed | — |
| Recovery path when a snapshot restore fails | Pending | — |
| Required evidence retention after emergency stop | Pending | — |
| CITEF incident/escalation procedure for unexpected external contact or modification | Pending | — |

## Zero-cost fallback matrix

Fallbacks keep development moving without silently changing the learning
objectives. A fallback must be explicitly accepted before it becomes the
delivery baseline.

| If CITEF cannot provide... | Zero-cost fallback | Effect on exercise | Decision |
|---|---|---|---|
| Eight separate logical hosts | Consolidate project-owned Linux services on `CTRL01`; keep Splunk, DC, and workstation separate | Lower infrastructure realism; objectives unchanged | Pending |
| Early access to CITEF VMs | Use local containers/processes and synthetic event fixtures for the vertical slice | Development only; CITEF rehearsal remains mandatory | Pending |
| VM snapshots | Idempotent Ansible reset plus versioned state/fixture manifests | Higher reset risk; must still meet the 20-minute target | Pending |
| Splunk during early development | Validate JSONL events and searches against fixtures; avoid building a new dashboard/SIEM | Development only; Splunk acceptance remains mandatory | Pending |
| Dedicated Splunk index | Isolate all content by mandatory `exercise_id` and `run_id` with CITEF-approved retention | More careful role/search filtering required | Pending |
| Splunk add-ons | Send normalized JSON through HEC or a monitored file with project-owned field mappings | Less native parsing; objectives unchanged | Pending |
| Participant AD privileges | Route allowlisted actions through the participant portal and action adapter | Learners demonstrate decisions through the exercise control instead of unrestricted admin access | Pending |
| Endpoint isolation tooling | Simulate isolation in the network/action adapter while preserving observable state | Must be clearly disclosed as simulated | Pending |
| Full Windows/AD telemetry | Generate deterministic surrogate events from the controlled adapter, labelled as simulated | Reduces platform realism; evaluator must not claim native coverage | Pending |
| Internet access | Pre-stage dependencies and use CITEF-approved offline artifact transfer | No effect during delivery; preparation lead time increases | Pending |
| Public-cloud services | Stateful Python mock already in scope | No scope change | Approved baseline |
| Safe real encryption | Marker and reversible move simulation already in scope | No scope change | Approved baseline |

## One-meeting agenda

Use this 60-minute agenda with the team and CITEF contact:

1. **5 minutes — Outcome and scope:** confirm that this is one blue-team
   operations exercise, not a general cyber-range platform.
2. **10 minutes — Audience and objectives:** approve participant profile,
   duration, five objectives, and four checkpoints.
3. **15 minutes — Topology and access:** map logical assets to VMs and confirm
   network, DNS, time, accounts, permissions, and dates.
4. **15 minutes — Splunk and evidence:** confirm version, ingestion, roles,
   retention, add-ons, and the telemetry acceptance method.
5. **10 minutes — Safety and reset:** confirm isolation, emergency stop,
   snapshot ownership, evidence preservation, and reset target.
6. **5 minutes — Decisions and owners:** select fallbacks, assign unanswered
   questions, record due dates, and identify approvers.

Send this document and the
[exercise-design package](README.md) at least two business days before the
meeting when possible.

## Decision and exception log

Record only decisions that change, constrain, or formally confirm the baseline.

| ID | Date | Decision or exception | Rationale/evidence | Owner | Affected docs/issues |
|---|---|---|---|---|---|
| D-001 | Pending | Blue-team-only MVP | Three-month delivery constraint and Cyber Range meeting direction | Team | All MVP work |
| D-002 | Pending | CITEF supplies Splunk | Avoids SIEM implementation and paid student resources | CITEF | #35, #79, #80 |
| D-003 | Pending | Python mock is the cloud boundary | No public cloud or cost required | Team/CITEF | #82 |
| D-004 | Pending | Marker mode replaces encryption | Protects range infrastructure and makes reset deterministic | Team/CITEF | #83 |

## Backlog re-estimation record

Complete this section after the requirements meeting.

| Milestone | Current target | Feasibility after confirmation | Change required |
|---|---|---|---|
| M1 — Design approval | Weeks 1–2 | Pending | — |
| M2 — Identity vertical slice | Weeks 3–4 | Pending | — |
| M3 — Complete scenario | Weeks 5–8 | Pending | — |
| M4 — Exercise operations | Weeks 9–10 | Pending | — |
| M5 — CITEF release | Weeks 11–12 | Pending | — |

Any change that consumes the protected Weeks 11–12 buffer must remove or defer
scope rather than assume additional student time or paid resources.

## Approval record

### Student team

- **Decision:** Pending
- **Representative:** Pending
- **Date:** Pending
- **Approved exceptions:** None recorded

### CITEF / Cyber Range

- **Decision:** Pending
- **Representative:** Pending
- **Role:** Pending
- **Date:** Pending
- **Approved exceptions:** None recorded

Approval may be recorded by an issue comment or meeting record from the named
representative; this document should then link to that evidence.

## Issue #76 completion checklist

- [ ] Team decisions table has no pending rows.
- [ ] All five learning objectives are approved or amended in the charter.
- [ ] A named CITEF contact is recorded.
- [ ] Logical assets are mapped to confirmed CITEF resources.
- [ ] Network, DNS, time, access, and automation constraints are recorded.
- [ ] Splunk version, ingestion, indexes, roles, retention, and add-ons are confirmed.
- [ ] Windows/AD and endpoint capabilities are confirmed.
- [ ] Safety, emergency-stop, snapshot, and reset ownership are confirmed.
- [ ] Every unavailable dependency has an accepted zero-cost fallback or scope reduction.
- [ ] The decision/exception log is current.
- [ ] Milestones and issues are re-estimated from confirmed constraints.
- [ ] Team and CITEF approval evidence is linked.
- [ ] Design documents and acceptance criteria reflect all approved changes.
