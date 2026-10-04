# NetStrike 12-Week Roadmap and Ownership

**Project:** Operation Silent Spider blue-team exercise

**Delivery window:** September 14–December 6, 2026

**Partner:** University of Ottawa Cyber Range

## Team ownership

| Person | Primary role | Owns |
|---|---|---|
| Aya Debbagh | Development lead | Architecture, controller, portal, integrations, safe actions, technical review |
| Ashley Goman | Client and project coordinator | Cyber Range communication, decisions, schedule, project board, risks, meeting follow-up |
| Patrick Luu | Splunk, environment, and testing lead | Splunk content, CITEF topology/configuration, offline deployment, readiness, rehearsals, defect evidence |
| Anna Brimacombe-Tanner | Exercise content and participant-experience lead | Injects, participant materials, facilitator/evaluator/solution content, usability and timing feedback |

Each owner is responsible for keeping their issues current and producing a
reviewable deliverable. Aya integrates technical changes, but documentation,
client coordination, telemetry validation, and exercise testing are not
treated as development-lead tasks.

## Milestones

### M1 — Design approval and contracts (September 14–27)

- Incorporate the Cyber Range response.
- Confirm the 2h50 total duration and snapshot restoration model.
- Publish the proposed tool/licensing/offline-install plan.
- Publish the dated roadmap and named team ownership.
- Merge the shared event and safe-action contracts.

**Exit:** the approved scope is reflected consistently in docs and issues;
remaining Cyber Range questions have a named owner.

### M2 — Identity vertical slice (September 28–October 11)

- Build the minimum controller run lifecycle and MSEL runner.
- Deliver the opening identity/helpdesk evidence.
- Ingest and find identity evidence in Splunk.
- Allow and verify safe participant containment.
- Export the run evidence and validate the restored snapshot.

**Exit:** one representative learner can complete the first scenario slice
from participant-facing information only.

### M3 — Complete scenario (October 12–November 8)

- Add endpoint/AD investigation and response.
- Add mock-cloud investigation and containment.
- Integrate the completed safe marker-impact and recovery adapter.
- Implement all four checkpoint branches and fallback evidence.

**Exit:** every planned branch can run safely and creates the expected
evidence.

### M4 — Exercise operations (November 9–22)

- Complete the participant and staff interfaces.
- Complete checkpoint scoring and after-action export.
- Finish participant, facilitator, evaluator, and solution guides.
- Run an internal usability rehearsal and correct timing/content problems.

**Exit:** someone outside the implementation can facilitate and evaluate the
exercise from the guides.

### M5 — Cyber Range release (November 23–December 6)

- Transfer and verify the offline installation bundle.
- Deploy on the approved Cyber Range topology.
- Capture clean snapshots and validate restore/readiness.
- Run at least two consecutive full rehearsals on clean restores.
- Fix release-blocking defects and package version 1.0.

**Exit:** Cyber Range stakeholders accept the exercise or record explicit
exceptions. Exact deployment, rehearsal, and delivery dates are coordinated
with Latifa.

## Working rhythm

- Two short team check-ins each week.
- One integration/rehearsal block each week from M2 onward.
- Ashley sends a weekly client status when there is a decision, risk, or
  dependency to report.
- Each person keeps no more than one major item in progress at a time.
- Every pull request has one teammate review and passing CI.
- Features that threaten the final two-week Cyber Range window are deferred.

## Current priority order

Updated October 4: all four scenario stages and application review/evidence
foundations are implemented locally; #134 and Patrick's #127/#128 are merged.
This is application progress, not live Cyber Range acceptance.

1. Connect human support to the existing consoles (#135), then surface existing
   staff readiness/clock/archive workflows without rebuilding the scenario.
2. Patrick proves offline deployment, identity-slice Splunk ingestion, privacy and
   snapshot/readiness on the approved range topology.
3. Anna finalizes content and records representative learner usability/timing and
   evaluator calibration; Aya integrates approved content and fixes application gaps.
4. Ashley confirms deployment/rehearsal/delivery dates and unresolved client decisions.
5. Complete representative full-play/range rehearsals, fix release-blocking defects
   and package the accepted version. Freeze optional additions before M5.

See [remaining development and the PR estimate](development-remaining-work.md).
