# Promoting a tested milestone to main

Feature PRs continue to target `dev`. `main` holds reviewed milestone snapshots,
not every development change. Development can continue while Patrick validates
a chosen candidate; record the exact commit he tested, not simply “latest dev”.
This checklist does not authorize a promotion or declare client acceptance.

## Two different milestones

| Milestone | Required evidence | What it does not claim |
| --- | --- | --- |
| Tested prototype | Green strict checks on the promotion candidate; teammate review; Patrick's offline install/application smoke record for that source and bundle; Anna's representative participant-flow check with limitations recorded. | Live range/Splunk/snapshot acceptance, calibrated scoring or final v1.0 approval. Local disposable VMs can supply the initial smoke evidence. |
| Accepted exercise v1.0 | Prototype checks plus approved content/calibration, deployed telemetry/access/readiness, two consecutive full clean-snapshot range rehearsals, resolved release blockers or explicit exceptions, and recorded stakeholder acceptance. | Success based only on automated developer personas or dashboard liveness. |

No December-only merge rule is needed. Promote meaningful tested milestones when
their evidence exists, then keep integrating feature PRs into `dev`.

## Automated application gate

`Local full-play rehearsal` runs on PRs and pushes to both `dev` and `main`, with
an optional manual run once this workflow version is available on the default
branch (`main`). Its existing `full-play-rehearsal` job name is retained.
It strictly runs all core Python suites (including package tooling and topology
validation), dependency-free Node interactions, all 24 local developer cases and
an independent export verification. Failures are not ignored.

Its additional `browser-smoke` job (#169) must also pass: it runs the existing
18-step journey through real browser forms/HTTP, export, recovery, mobile evidence
and reset in managed Chromium. Preserve the source-correlated screenshots/receipt
alongside other evidence. This is one compressed synthetic developer path, not
representative usability or a replacement for any owner acceptance requirement.
See [browser scope and commands](ui-walkthrough.md#strict-real-browser-smoke-gate-169).

The separate [maintained application security gate](application-security-gate.md)
blocks medium/high Bandit findings and scan errors in application/tooling code
and the five maintained profile/action adapters. Legacy reports remain
informational, not evidence those entry points passed.

The final verification uses `--require-current-source`: the package must record
the current clean Git commit and exactly match the recorded application/source
fingerprint map. Missing Git metadata, dirty or unknown status, changed commits
or missing/extra/changed fingerprints fail this gate. Matching a subset does not
prove full coverage; CI executes the full suite without `--case`. Historical
packages remain inspectable with ordinary `--verify`, without the checkout check.

On a PR, Actions normally tests a temporary merge commit. That is not necessarily
the feature head or the final merge commit. A green PR check is required, then the
post-merge `main` run must pass as well. Use the final immutable commit when
building the release bundle and collecting final deployment evidence. An older
offline smoke test is useful progress but does not automatically cover changed
application files; document the tested revision and retest changed behavior.

This workflow is a check, **not branch protection**. At the 5 October inspection,
neither main nor dev had branch protection. A repository administrator should
require review and the strict check if available under the repository's settings;
until then, reviewers must enforce the checklist manually. This increment does
not change repository settings. [Module pytest and coverage](ci-evidence-checks.md)
now fail on errors; module lint alone remains informational. Missing test suites
are explicitly not validation and do not generate coverage artifacts.
The security job now has strict maintained-code scans alongside the informational
legacy-module report; require its `bandit` check as well.

## Promotion PR record

Open one `dev` → `main` PR only when the selected milestone has its evidence.
If dev advances, inspect the changed files and rerun/reconcile evidence before
merging; evidence for an older candidate is not blanket approval for new changes.
Do not rewrite shared branch history or bypass checks to match a tested version.

Copy this record into the promotion PR; keep secrets and staff exercise answers
out of public/client-facing attachments:

```text
Milestone: tested prototype / accepted v1.0
Candidate dev commit:
Promotion PR and tested merge commit / strict Actions run URL:
Teammate reviewer:
Offline build workflow run URL and inventory repository revision:
Downloaded bundle SHA-256 and approved preserved artifact location:
Inventory SHA-256 recorded from trusted staging / selected-source check JSON:
Patrick: VM image/architecture, disconnected install/smoke result, defects:
Anna: participant-flow/content check, unresolved usability/calibration limits:
Ashley: dates/decision links and acceptance status (pending is not accepted):
Remaining blockers/exceptions and owners:
After merge: final main commit, passing strict run, matching rebuilt bundle:
```

The offline builder is manually dispatched. Explicitly select the intended
source branch or existing tag when running it (for example, `gh workflow run
offline-bundle.yml --ref dev`). Record the workflow's resolved commit and confirm
it is the selected candidate in `inventory.json`; branch names can move. Build
again from final main for release and verify its resolved immutable commit.
Do not assume a bundle built from the default branch includes the current dev
application. Record the downloaded
archive SHA-256 separately from the bundle's internal `SHA256SUMS`; neither is
a signature. Retain approved artifacts before the 14-day CI retention expires.

Use the [read-only offline source checker](offline-release-source-check.md) before
starting the extracted source to compare the saved expected revision/inventory
digest with the selected six source trees. This does not verify whole-bundle
installation or code already loaded by a process.

Do not create an accepted-release tag or promise client readiness while final
owner checks are pending. After promotion, continue feature PRs into dev.

## Responsibility boundary

- Aya: application checks, integration defects, source/release consistency.
- Patrick: bundle/licensing and disconnected VM installation evidence,
  Windows/Sysmon/Splunk, topology, snapshots and actual range rehearsals.
- Anna: exercise wording, real participant usability/timing and rubric calibration.
- Ashley: client communication, dates, decisions and acceptance coordination.

See [offline bundle and smoke procedure](offline-bundle.md),
[local rehearsal limitations](local-rehearsal.md),
[deployment inputs](application-deployment-contract.md) and
[remaining work](development-remaining-work.md).
