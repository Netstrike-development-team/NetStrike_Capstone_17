# Remaining development and PR estimate — 5 October 2026

This is a planning estimate, not a list of confirmed defects or a promise of an
exact PR count. Baseline: #148 merged; Patrick's #127/#128/#139/#140 also merged. The
application already supports all four checkpoint branches, mock-cloud and safe
impact/recovery, submissions, human review/AAR, run archives, supervised timing,
private event-spool export, local readiness, human support and staff operations.

**Aya: approximately 2–4 planned development PRs, including current offline-source
handoff (#149) and approved content integration, plus 3–6 rehearsal-driven fix PRs:
budget 5–10 in total.** Smaller fixes
can be combined; a significant integration defect can require several PRs. This
is not a plan for new major features. Strict milestone checks are merged in #148;
#149 completes the second source/handoff increment already allowed below. Freeze optional features before the
final Cyber Range delivery window.

| Remaining work package | Planning allowance | Exit evidence / boundary |
| --- | --- | --- |
| Connect private support requests/replies and evaluator transcript to the existing consoles | Delivered in #136; #135 closed | Client-state/API regressions and owner handoff; Anna still validates usability/content. |
| Surface existing readiness, supervised-clock and archive operations in staff workflows | Delivered in #138; #137 closed | Staff diagnostics, run-scoped commands/exports and saved reviews integrated locally; owner usability/live acceptance remain. |
| Load Anna's final exercise content and reconcile screens/instructions | 1 PR | Approved injects, wording and objective labels match the 2h50 session. Aya integrates; Anna authors and signs off. |
| Application/deployment contract integration | Startup contract delivered in #142; #141 closed; allow 0–1 evidence-driven follow-up | Read-only deployment-input preflight/fail-before-write startup is implemented. Patrick still proves the deployed application/readiness/private spool; Aya fixes evidenced application gaps, not Patrick's Ansible/Splunk backlog. |
| Cross-role full-play workflow and integration checks | Delivered in #144; #143 closed | Learner run-pinning closes an observed reset gap; representative HTTP roles compose checkpoints, recovery, terminal stop/completion, private archives, reset and fresh actions. Existing 24-case service tests stay unchanged; local checks do not replace real learner/range rehearsals. |
| Reliable current human review workflow | Delivered in #146; #145 closed | Same-revision drafts preserved; downloads pin run/report snapshot; unconfirmed saves require inspection. Anna's rubric/calibration and Patrick's real acceptance remain separate. |
| Application release/handoff consolidation | Strict gates delivered in #148; #147 closed. 1 current PR (#149); final reconciliation can share an owner-driven fix | Dependency-free selected-bundle source check against expected commit/inventory digest. Prototype versus v1.0 gates remain separate; final package/configuration/support agreement depends on owner evidence. Ashley coordinates sign-off. |

Several packages can share a PR. The allowances describe reviewable increments,
not seven independently mandatory new products. Restart/resume of an in-flight
exercise, an automated numeric grade and learner-operated red teaming are **not**
new MVP promises. After #149, prioritize approved content integration and actual
deployment/usability/rehearsal defects rather than inventing new features while
owner evidence is pending. The application remains process/run scoped; a process fault
requires stop, evidence preservation and the documented restore procedure.

## Why open issues are not a feature count

There were 27 open issues at the earlier #134 planning read, including merged #133
awaiting tracker reconciliation. Many are overlapping epics (#27/#33/#34/#35) or acceptance
wrappers (#80–#86). Identity, cloud, recovery and AAR issues deliberately remain
open until representative learners and the actual range supply acceptance evidence.
Their open status does not mean those stages still need to be built from scratch.

Patrick owns offline installers/licenses, concrete topology, Splunk configuration,
data-health and ingestion proof, snapshots/readiness and acceptance rehearsals
(#101–#104). Anna owns inject scripts, participant and facilitator/evaluator/solution
materials, timing/usability and calibration (#98–#100). Ashley owns schedule,
client decisions, risk/board and final acceptance coordination (#96/#97). Aya
owns application integration and code fixes found by that work.

For **all team repository work**, a rough allowance is **10–18 further PRs**,
including Aya's work and possible environment/content/release updates. Non-code
deliverables can instead be linked directly to issues; they do not need artificial
PRs. This wider estimate has lower confidence until deployment and the first
representative rehearsal. PR count measures batching, not percent complete.

## Most important next gates

1. Patrick validates the deployed identity slice and searchable run-correlated
   sources, including staff/participant separation; addresses deployment blockers.
2. Anna and a non-author test the real learner flow and final content rather than
   accepting a developer's automated success path as usability proof.
3. The team records objective calibration and complete live rehearsals, including
   two consecutive clean-snapshot range runs. Aya fixes evidenced code defects.
4. Ashley obtains deployment/rehearsal/delivery dates and acceptance decisions.

Re-estimate after the first deployed slice, the first representative full-play
rehearsal and the first clean-snapshot range rehearsal. Local tests and passing
CI do not establish live Splunk ingestion, snapshot restoration or client sign-off.
