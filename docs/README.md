# Documentation index

This index covers the repository's Markdown files, including component guides
and archived/legacy placeholders. Guides are grouped into topic folders;
follow the task routes below or open a folder index to browse its contents.
Short descriptions indicate whether a file is operational guidance, a contract,
a planning snapshot, or only a placeholder.

## Find a guide by task

| If you need to… | Start with |
|---|---|
| Understand the exercise and its requirements | [Exercise design package](exercise-design/README.md) |
| Prepare or run an exercise | [Full-play deployment runbook](deployment/full-play-deployment-guide.md), [staff operations](operations/staff-operations.md), and [participant safety](operations/participant-run-safety.md) |
| Build or validate an offline deployment | [Offline bundle guide](deployment/offline-bundle.md) and [validation report](deployment/offline-bundle-provisioning-validation.md) |
| Change application behavior or integrations | [Architecture](application/architecture.md), then the relevant [contract](#contracts-and-application-behavior) |
| Find implementation-level setup | [Application and component guides](#application-and-component-guides) and [scenario module guides](#scenario-module-guides) |

## Folder guide

| Folder | Contents |
|---|---|
| [`application/`](application/README.md) | Architecture, application behavior, and versioned contracts |
| [`deployment/`](deployment/README.md) | Deployment inputs, offline bundles, provisioning, and release checks |
| [`development/`](development/README.md) | Roadmap, developer handoffs, and local rehearsals |
| [`exercise-design/`](exercise-design/README.md) | Exercise scope, storyline, safety, and approval materials |
| [`evidence/`](evidence/README.md) | Dated verification and CI evidence; treat these as scoped snapshots |
| [`network-diagram/`](network-diagram/README.md) | Editable PlantUML sources and rendered topology diagrams |
| [`operations/`](operations/README.md) | Staff, participant, and evaluator workflows |
| [`script/`](script/README.md) | Briefing script and participant quick reference |

## Start here

| Document | What it covers |
|---|---|
| [Exercise design package](exercise-design/README.md) | Accepted exercise scope, design documents, and outstanding approval gates |
| [Architecture](application/architecture.md) | MVP components, boundaries, and out-of-scope work |
| [Roadmap and ownership](development/roadmap.md) | Delivery milestones, schedule, team roles, and working rhythm |
| [Remaining development estimate](development/development-remaining-work.md) | Planning estimate updated October 7, 2026; not a live issue count or delivery commitment |
| [Repository README](../README.md) | Project overview, current state, repository structure, and development workflow |

## Exercise design documents

These are the detailed design and approval materials linked from the [package
index](exercise-design/README.md).

| Document | What it covers |
|---|---|
| [01 — Exercise charter](exercise-design/01-exercise-charter.md) | Audience, prerequisites, staffing, objectives, roles, and permitted actions |
| [02 — Storyline and MSEL](exercise-design/02-storyline-and-msel.md) | Narrative, known truth, decision branches, inject schedule, and pacing |
| [03 — Telemetry and evidence matrix](exercise-design/03-telemetry-evidence-matrix.md) | Required sources, evidence, Splunk views, and evidence-quality rules |
| [04 — Safety and reset](exercise-design/04-safety-and-reset.md) | Safety controls, emergency stop, snapshot restoration, and readiness |
| [05 — Guide outlines](exercise-design/05-guide-outlines.md) | Participant, facilitator, evaluator, solution, and AAR guide structures |
| [06 — CITEF requirements and approval](exercise-design/06-citef-requirements-and-approval.md) | Environment questionnaire, decisions, fallbacks, backlog, and approval record |
| [07 — Offline tool-bundle inventory](exercise-design/07-offline-tool-bundle-inventory.md) | Software/artifact inputs, licensing gates, deployment decisions, and test record |
| [Briefing and participant reference drafts](script/README.md) | Revised opening/15-minute script, learner-safe templates, and owner checklist; pending content, deployment and non-author approval |

## Contracts and application behavior

| Document | What it covers |
|---|---|
| [Exercise event contract v1](application/contracts/event-contract-v1.md) | Canonical event schema, compatibility rules, producer/consumer requirements, and Splunk envelope |
| [Safe-action contract v1](application/contracts/safe-action-contract-v1.md) | Authorization, validation, execution, rollback, and audit requirements for state-changing actions |
| [Synthetic profile contract v1](application/contracts/synthetic-profile-contract-v1.md) | Maintained synthetic identity input, validation, and runtime configuration |
| [Application-event spool](application/event-spool.md) | Local export of the canonical event ledger and the separate Splunk/visibility acceptance work |
| [Application readiness](application/application-readiness.md) | Local preflight, guarded preparation/start, and the boundary from range approval |
| [Application security gate](application/application-security-gate.md) | Blocking maintained-code scans, informational legacy boundary and recorder loopback request controls |
| [Application telemetry comparison](application/application-telemetry-comparison.md) | Read-only canonical ledger versus saved raw receiver-export comparison; not live ingestion or readiness proof |

## Exercise operations

| Document | What it covers |
|---|---|
| [Learner-safe Splunk audit](operations/learner-splunk-audit.md) | Separate fact-only SimCorp application evidence, participant investigation workflow and live handoff |
| [Learner audit/export comparison](operations/learner-telemetry-comparison.md) | Read-only comparison of published learner evidence with an independently supplied Splunk Raw Events export |
| [Supervised exercise clock](operations/exercise-clock.md) | Staff clock inspection, supervision, failure behavior, and recovery |
| [Human support workflow](operations/exercise-support.md) | Private learner requests, staff replies, roles, and API lifecycle |
| [Run-review archives](operations/run-review-archives.md) | Capture and retrieval of frozen run-review snapshots across application reset |
| [Offline staff operations](operations/staff-operations.md) | Staff readiness/clock controls and saved-review UI workflows, role and restore limits |
| [Learner reset safety](operations/participant-run-safety.md) | Run-pinned learner actions/submissions, stale-page and delayed-response boundaries |
| [After-action review](operations/after-action-review.md) | Human objective review, submissions, and offline AAR generation |
| [Current evaluator workflow](operations/evaluator-review-workflow.md) | Draft preservation, revision-safe saves and run/snapshot-pinned raw exports |

## Developer demos and rehearsal

| Document | What it covers |
|---|---|
| [Scheduled synthetic MFA](development/scheduled-mfa-dev-handoff.md) | Local MFA role-play sequence and browser demo |
| [Mock-cloud stage](development/mock-cloud-dev-handoff.md) | Opt-in identity/cloud scenario, tools, evidence, and development boundaries |
| [Impact and recovery](development/impact-recovery-dev-handoff.md) | Opt-in full-play path, disposable-file impact, recovery, and team handoff |
| [Local full-play rehearsals](development/local-rehearsal.md) | Offline execution and verification of the 24-case developer regression package |
| [Evidence UI walkthrough](development/ui-walkthrough.md) | Participant evidence boundary and reproducible local browser recording |

## Deployment and offline operation

| Document | What it covers |
|---|---|
| [Application deployment inputs](deployment/application-deployment-contract.md) | Offline read-only configuration inspection before startup side effects; not runtime/range readiness |
| [Full-play deployment runbook](deployment/full-play-deployment-guide.md) | Provisioning steps, post-deployment verification, and safe next-run handoff |
| [Offline bundle build and install](deployment/offline-bundle.md) | Building, verifying, installing, and smoke-testing the Python bundle |
| [Offline bundle and provisioning validation](deployment/offline-bundle-provisioning-validation.md) | November 1, 2026 screenshot evidence, accepted DNS-blocking evidence, observed readiness and provisioning limits; not final exercise sign-off |
| [Actual offline full-play smoke](deployment/offline-fullplay-smoke.md) | Kernel-isolated packaged runtime/HTTP workflow gate and evidence boundaries |
| [Splunk Sysmon ingestion](deployment/splunk-sysmon-ingest.md) | Configure the Splunk receiver and test Windows Sysmon forwarding |
| [Offline application source check](deployment/offline-release-source-check.md) | Read-only selected-source comparison against a separately recorded commit/inventory digest, without Git or runtime dependencies |
| [Milestone promotion checklist](deployment/milestone-release-checklist.md) | Strict main/dev checks, source-matched evidence and prototype versus accepted-release gates |
| [CI test and coverage evidence](evidence/ci-cd-trends-2026-10-19/ci-evidence-checks.md) | Strict module test outcomes, retained coverage, no-tests boundaries and pinned Node-24 actions/CI image |
| [CI/CD quality trends](evidence/ci-cd-trends-2026-10-19/ci-cd-overview.md) | Weekly averages since September 1: coverage, test-count-weighted pass rate, tests per run, workflow success, and evidence gaps |
| [CITEF topology and Ansible workflow](../citef-config/README.md) | Team-controlled topology under delegated range authority, private manifest, provisioning, and post-restore checks; configuration permission is established |

## Application and component guides

These explain code-level usage and component boundaries; use the contracts and
exercise-design package above for normative interface and exercise requirements.

| Document | What it covers |
|---|---|
| [Dashboard and portal API](../dashboard/README.md) | Portal routes, authentication, APIs, and links to operational workflows |
| [Scenario controller](../orchestrator/README.md) | MSEL execution, scheduling, evidence export, integrations, and developer use |

## Scenario module guides

| Document | What it covers |
|---|---|
| [Module 01 — OSINT profiler](../modules/01-osint-profiler/README.md) | Legacy simulated OSINT pipeline and profile output; maintained runtime input is separately documented in the [profile contract](application/contracts/synthetic-profile-contract-v1.md) |
| [Module 02 — Phishing infrastructure](../modules/02-phishing-infra/README.md) | Stub that directs readers to the repository overview; no module-specific guidance |
| [Module 03 — Vishing scripts](../modules/03-vishing-scripts/README.md) | Stub that directs readers to the repository overview; no module-specific guidance |
| [Module 04 — Synthetic MFA and identity](../modules/04-mfa-fatigue-sim/README.md) | Safe identity actions and state; notes the standalone Flask harness is legacy |
| [Module 05 — Endpoint and Active Directory](../modules/05-lateral-movement/README.md) | Safe endpoint/AD simulation and separate legacy LDAP evidence generator |
| [Module 06 — Mock-cloud containment](../modules/06-cloud-exfil/README.md) | Mock-cloud state and safe containment; distinguishes a standalone legacy demo |
| [Module 07 — Marker impact and recovery](../modules/07-ransomware-sim/README.md) | Safe marker-only impact and recovery boundaries |
| [Module 07 usage](../modules/07-ransomware-sim/USAGE.md) | Exercise integration, branch behavior, legacy demo, and verification |

## Choosing a source of truth

- Use the exercise-design package for approved exercise intent, safety, and
  delivery requirements. The [CITEF approval pack](exercise-design/06-citef-requirements-and-approval.md)
  owns range decisions; the [offline tool-bundle inventory](exercise-design/07-offline-tool-bundle-inventory.md)
  owns artifact choices and deployment evidence.
- Use the [CITEF configuration guide](../citef-config/README.md) for the
  manifest and Ansible commands, not as an approval record. The
  [offline bundle guide](deployment/offline-bundle.md) owns bundle build/install steps;
  the dated validation report records one scoped local rehearsal.
- Use versioned contracts for interface requirements. Developer handoffs
  describe a particular implementation and do not replace those contracts.
- Treat dated reviews, local verification receipts, and development estimates as
  snapshots. They are not evidence of current deployment, live Splunk
  acceptance, or Cyber Range sign-off.
- The component READMEs above remain the entry points for current setup and
  code-level usage. Stub and archived files are identified explicitly.
- Markdown files under `_legacy/` are intentionally not indexed; they describe
  retired project structure rather than current guidance.
