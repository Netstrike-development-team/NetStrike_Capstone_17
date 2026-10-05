# Documentation index

This index covers the repository's Markdown files, including component guides
and archived/legacy placeholders. Documents remain at their existing paths so
current links keep working. Short descriptions indicate whether a file is
operational guidance, a contract, a planning snapshot, or only a placeholder.

## Start here

| Document | What it covers |
|---|---|
| [Exercise design package](exercise-design/README.md) | Accepted exercise scope, design documents, and outstanding approval gates |
| [Architecture](architecture.md) | MVP components, boundaries, and out-of-scope work |
| [Roadmap and ownership](roadmap.md) | Delivery milestones, schedule, team roles, and working rhythm |
| [Remaining development estimate](development-remaining-work.md) | Planning estimate dated October 5, 2026; not a live issue count or delivery commitment |
| [Integration review](patrick-integration-review-2026-10-03.md) | Historical October 3 review of proposed deployment PRs and risks; not current deployment or acceptance status |
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

## Contracts and application behavior

| Document | What it covers |
|---|---|
| [Exercise event contract v1](event-contract-v1.md) | Canonical event schema, compatibility rules, producer/consumer requirements, and Splunk envelope |
| [Safe-action contract v1](safe-action-contract-v1.md) | Authorization, validation, execution, rollback, and audit requirements for state-changing actions |
| [Synthetic profile contract v1](synthetic-profile-contract-v1.md) | Maintained synthetic identity input, validation, and runtime configuration |
| [Application-event spool](event-spool.md) | Local export of the canonical event ledger and the separate Splunk/visibility acceptance work |
| [Application readiness](application-readiness.md) | Local preflight, guarded preparation/start, and the boundary from range approval |
| [Application deployment inputs](application-deployment-contract.md) | Offline read-only configuration inspection before startup side effects; not runtime/range readiness |
| [Supervised exercise clock](exercise-clock.md) | Staff clock inspection, supervision, failure behavior, and recovery |
| [Human support workflow](exercise-support.md) | Private learner requests, staff replies, roles, and API lifecycle |
| [Run-review archives](run-review-archives.md) | Capture and retrieval of frozen run-review snapshots across application reset |
| [Offline staff operations](staff-operations.md) | Staff readiness/clock controls and saved-review UI workflows, role and restore limits |
| [Learner reset safety](participant-run-safety.md) | Run-pinned learner actions/submissions, stale-page and delayed-response boundaries |
| [After-action review](after-action-review.md) | Human objective review, submissions, and offline AAR generation |

## Developer demos and rehearsal

| Document | What it covers |
|---|---|
| [Scheduled synthetic MFA](scheduled-mfa-dev-handoff.md) | Local MFA role-play sequence and browser demo |
| [Mock-cloud stage](mock-cloud-dev-handoff.md) | Opt-in identity/cloud scenario, tools, evidence, and development boundaries |
| [Impact and recovery](impact-recovery-dev-handoff.md) | Opt-in full-play path, disposable-file impact, recovery, and team handoff |
| [Local full-play rehearsals](local-rehearsal.md) | Offline execution and verification of the 24-case developer regression package |
| [Evidence UI walkthrough](ui-walkthrough.md) | Participant evidence boundary and reproducible local browser recording |

## Deployment and offline operation

| Document | What it covers |
|---|---|
| [Offline bundle build and install](offline-bundle.md) | Building, verifying, installing, and smoke-testing the Python bundle |
| [CITEF requirements and approval](exercise-design/06-citef-requirements-and-approval.md) | Environment questionnaire, decision log, fallbacks, and approval records |
| [CITEF topology and readiness](../citef-config/README.md) | Proposed infrastructure, manifest, provisioning, post-restore readiness, and acceptance; proposed, not deployment approval |
| [Offline tool-bundle inventory](exercise-design/07-offline-tool-bundle-inventory.md) | Software inputs, approvals, and artifact handling |

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
| [Module 01 — OSINT profiler](../modules/01-osint-profiler/README.md) | Legacy simulated OSINT pipeline and profile output; maintained runtime input is separately documented in the [profile contract](synthetic-profile-contract-v1.md) |
| [Module 02 — Phishing infrastructure](../modules/02-phishing-infra/README.md) | Stub that directs readers to the repository overview; no module-specific guidance |
| [Module 03 — Vishing scripts](../modules/03-vishing-scripts/README.md) | Stub that directs readers to the repository overview; no module-specific guidance |
| [Module 04 — Synthetic MFA and identity](../modules/04-mfa-fatigue-sim/README.md) | Safe identity actions and state; notes the standalone Flask harness is legacy |
| [Module 05 — Endpoint and Active Directory](../modules/05-lateral-movement/README.md) | Safe endpoint/AD simulation and separate legacy LDAP evidence generator |
| [Module 06 — Mock-cloud containment](../modules/06-cloud-exfil/README.md) | Mock-cloud state and safe containment; distinguishes a standalone legacy demo |
| [Module 07 — Marker impact and recovery](../modules/07-ransomware-sim/README.md) | Safe marker-only impact and recovery boundaries |
| [Module 07 usage](../modules/07-ransomware-sim/USAGE.md) | Exercise integration, branch behavior, legacy demo, and verification |

## Choosing a source of truth

- Use the exercise-design package for approved exercise intent, safety, and
  delivery requirements; record environment-specific decisions in its approval
  pack.
- Use versioned contracts for interface requirements. Developer handoffs
  describe a particular implementation and do not replace those contracts.
- Treat dated reviews, local verification receipts, and development estimates as
  snapshots. They are not evidence of current deployment, live Splunk
  acceptance, or Cyber Range sign-off.
- The component READMEs above remain the entry points for current setup and
  code-level usage. Stub and archived files are identified explicitly.
- Markdown files under `_legacy/` are intentionally not indexed; they describe
  retired project structure rather than current guidance.
