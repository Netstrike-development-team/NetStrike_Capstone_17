# Objective review and offline after-action report

Issue #84 development milestone, not calibrated grading or Cyber Range sign-off.
Aya owns the implementation; Anna owns rubric/content review; Patrick/team own
representative runs and evaluator calibration. No new paid tool or Internet
access is needed. This extends the existing air-gapped FastAPI portal, not a
hosted Sites project.

## Run and review

1. Participants can submit six to twelve significant timeline entries through
   their console before the selected scenario's DP2 containment deadline. Each
   entry has a timezone-aware occurrence timestamp, fact/inference label,
   supporting current-run visible event ID and learner statement. The receipt
   contains no answer key. Truth, ordering, significance, source coverage and
   inference quality remain human judgments.
2. Stop or complete play before recording objective ratings. Stopped partial
   runs can be reviewed; they are not completed exercises.
3. Open `/evaluator` (linked from the facilitator console). Configure a unique
   actor and newly generated token of at least 24 characters with role
   `evaluator` in `NETSTRIKE_PORTAL_TOKENS`. There is no built-in credential.
   Evaluators cannot start, advance, resolve, stop or reset play. Facilitators
   may also evaluate; technical operators and participants may not.
4. Select an objective. Review the machine observation, charter criteria,
   human-review requirements and submitted evidence. Cite current-run event IDs
   or `submission:<id>` references. Record a rating and rationale.
5. `Not observed` requires a platform/exercise-control explanation. Observed
   ratings require evidence. Positive ratings against a failed machine subset,
   or any observed rating when machine evidence is unavailable, require an
   explained, evidenced override. Do not invent alternative observations.
6. Record improvements with description, owner, priority and target date or
   milestone. The UI supports one action per judgment; the API supports five.
7. Corrections require the current revision and a reason. New events link to
   prior judgments; previous evaluator, rationale, timestamp and references
   remain available. Conflicting/stale writes fail. Reviews never alter branches.
8. Download the offline bundle and Markdown AAR for a durable copy. Application
   reset now also preserves a staff-only [frozen review archive](run-review-archives.md).
   Export outside restored VMs before hypervisor snapshot restoration. A terminal run
   with five ratings is `reviewed`: this means review completeness, not external
   acceptance. Unrated objectives are not zeroes.

Hints, support, valid alternate procedures and platform faults must be reflected
in the evaluator's rationale and appropriate charter rating. Never enter
credentials or personal information into free-text fields.

## Mapping and limits

| Objective | Machine observation | Human review |
|---|---|---|
| LO1: triage | DP1 result and 25-minute deadline from first inject, in exercise time | Artifact relevance, interpretation and defensible classification |
| LO2: reconstruct | Human review required; no automatic prose grade | Six significant events, at least five correct, ordering, sources, fact/inference distinction and deadline |
| LO3: contain | DP2 verifier result and frozen boolean checks | Preservation sequence, response rationale and collateral disruption |
| LO4: cloud exposure | DP3 state/evidence result and frozen checks | Bucket identification, interpretation and confirmed vs unproven exposure |
| LO5: recover/communicate | Frozen end-of-play recovery observation/checks | Truth, clarity, remaining risk and prioritized recommendations |

All four checkpoint rubric definitions are included in JSON. DP4 maps to
LO3/LO5 and records prevention only: it does not automatically award LO5.
Final recovery remains a separate observation, not a fifth branching checkpoint.
Legacy exports without individual checks retain their aggregate observation;
the new producers include frozen verifier booleans.

Missing checkpoint/final evidence, missing identity timing and absent verifier
state are `not_observed`, not learner failure. LO2 always requires human review.
Free text is never graded by string matching or AI.

The charter's suggested **40/35/15/10** assessment-dimension weighting is kept
as metadata. `aggregate_score` remains null: numeric grading needs approved
criterion weights and evaluator calibration, not invented conversions of
ordinal ratings.

Participant feedback is available only after terminal play and all five reviews.
It includes ratings and generic practice suggestions, never staff prose,
verifier checks, identifiers, branches, raw events or answer keys.

## Offline report generation

```bash
python scripts/generate_aar.py run-review-bundle.json
python scripts/generate_aar.py run-review-bundle.json --format json
python scripts/generate_aar.py run-review-bundle.json --format feedback
```

The command prints to stdout. It does not modify the bundle, write files,
start services or contact the Internet. Feedback refuses incomplete review.
The Markdown report includes objective results, evidence, revision history,
platform observations, corrective owners and the facilitator timeline in
**ingestion order**. JSON also preserves complete redacted submissions and
structured rubric metadata. Do not mistake ingestion order for occurrence order.

Bundles use bundle/rubric version 1.0.0 and include events plus submissions.
Validation rejects incompatible versions, mixed runs, duplicate/out-of-order
events, invalid canonical events, bad review roles/objective bindings, unknown
references and inconsistent revision chains. CLI input is limited to 20 MiB.
SHA-256 detects accidental modification; it is **not a signature** or independent
proof of evaluator identity. Someone able to rewrite and rehash an export can
forge content. Preserve the original and its trusted server provenance.

Bearer configuration and private runtime state are not serialized. Key-based
redaction cannot guarantee arbitrary prose contains no sensitive information;
use synthetic content and review staff exports before sharing. Markdown escapes
staff-authored HTML and link markup. Participant feedback never copies this prose.

## API

| Endpoint | Roles |
|---|---|
| `POST /api/participant/timeline` | Participant |
| `GET /api/evaluator/report` | Evaluator/facilitator |
| `POST /api/evaluator/judgments` | Evaluator/facilitator |
| `GET /api/evaluator/exports/bundle.json` | Evaluator/facilitator |
| `GET /api/evaluator/exports/aar.md` | Evaluator/facilitator |
| `GET /api/participant/feedback` | Participant, after complete review |

Judgment input: `run_id`, `objective_id`, `rating`, `rationale`, `evidence_ids`,
`expected_revision`, `override_reason`, `platform_reason`, `improvement_actions`.
Actor/role come only from authentication. Each action has `description`, `owner`,
`priority` (`high/medium/low`) and `target_date`. Run and revision checks prevent
stale reviews crossing reset.

## Remaining #84 acceptance

- Anna reviews indicators, scoring examples, hint/support treatment and numeric
  weighting if required; guides document unavailable/out-of-band artifacts.
- The team chooses a calibration consistency threshold and two evaluators
  independently score the same run. This implementation does not claim that
  calibration has happened.
- Patrick/team verify real sources and learner flows on the air-gapped range.
  Local synthetic runs do not prove Splunk or Cyber Range readiness.
- Rehearsals cover partial runs, missing telemetry, every branch, concurrent
  reviewers, export before reset and clean-snapshot restoration.
