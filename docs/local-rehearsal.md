# Local full-play developer rehearsals

The rehearsal runner checks the real in-process portal service, scenario
controller and safe identity, endpoint, mock-cloud and disposable-file adapters.
It does not start a web server, contact Splunk, use Internet access, provision VMs
or submit human evaluator judgments. The exercise clock is accelerated.

## Run it

Use the repository's Python environment (Python 3.11 or newer), with the
dependencies in `dashboard/requirements.txt` installed. From the repository root:

```sh
# Inert preview: list the reviewed cases; no services, files or Git queries.
python scripts/rehearsal.py

# Execute all 24 cases. The parent must exist; the output directory must be new.
python scripts/rehearsal.py --execute --output /tmp/silent-spider-rehearsal

# Optional single-case rehearsal, in another new directory.
python scripts/rehearsal.py --execute --output /tmp/silent-spider-single \
  --case path-pass-pass-pass-pass

# Read-only review of an exported package; no live database required.
python scripts/rehearsal.py --verify /tmp/silent-spider-rehearsal
```

Repeat `--case` to select multiple distinct cases. Unknown or duplicate cases
are refused before any output is created. Existing output directories, files
and symlinks are never overwritten. This is a CLI test tool, not a UI walkthrough.
Install dependencies before transferring the code to an air-gapped environment;
execution and verification themselves require no network.

## Coverage

The sixteen `path-*` cases cover all pass/miss combinations for DP1 through DP4.
They use actual permitted actions and current-run evidence to reach checkpoints;
they do not directly assign checkpoint results. Each normal case completes the
play clock, exercises recovery, exports its observations and checks reset readiness.

Eight additional cases check incomplete controls and fail-safe behavior:

| Case | Expected technical behavior |
| --- | --- |
| `partial-cloud-control` | Revoked key prevents further exposure even though incomplete containment misses DP3. |
| `partial-impact-control` | Stopped task blocks simulated impact even though incomplete containment misses DP4. |
| `missing-cloud-source` | Missing audit evidence blocks cloud grading; stop safely. |
| `cloud-telemetry-fault` | Failed cloud evidence delivery remains a visible fault; stop safely. |
| `missing-impact-source` | Missing endpoint source blocks impact grading; stop safely. |
| `impact-write-fault` | An injected second-marker write failure rolls back partial changes. |
| `stop-during-impact` | A stop during the second marker cancels work and restores decoys. |
| `recovery-write-fault` | An injected partial restoration failure rolls back and does not claim recovery. |

An expected fault is a passing guard test, not a successful exercise completion.
Fault cases remain stopped, without a fabricated final recovery grade. A technical
regression produces a nonzero exit status and retains available failure evidence.

## Evidence package

`manifest.json` records selected cases, source-file SHA-256 fingerprints, optional
Git revision and dirty-tree status, runtime details and artifact hashes. Git is
optional: an exported source tree can run without repository metadata. The hashes
describe the source actually used; a dirty checkout is not claimed to match its
commit. These are modification checks, not signatures or proof of authorship.

Each case retains:

- `events.jsonl`: the canonical original-run event ledger;
- `reset-events.jsonl`: the separately correlated fresh-run ledger;
- `run-review-bundle.json`: the portable review inputs;
- `after-action-review.md`: a provisional AAR, with no human ratings;
- `result.json`: expected versus observed technical checks and reset results;
- `disposable/`: old and new run decoys, restored byte-for-byte to their baseline.

If reset or report export fails, `failure.json` and available ledgers are retained
instead. A failed or incomplete package cannot be verified as successful.

The read-only verifier checks hashes and regular-file safety, reproduces the AAR
from its bundle, checks the fixed case's checkpoint and outcome expectations,
validates event/reset correlation, and independently inspects both retained decoy
baselines. It does not trust a summary flag alone. A subset reports `full_suite:
false`; only all 24 reviewed cases count as full coverage. Packages contain staff
answer/evaluation information: do not distribute them as participant materials.

## CI and responsibility boundary

The `Local full-play rehearsal` workflow runs regression tests, executes all
24 cases, verifies the exported package independently and uploads the evidence
with a 14-day retention period. Failures fail the job; evidence upload still runs.
This adds a CI check, not a change to repository branch-protection rules.

Aya owns this developer regression harness. Anna owns participant experience,
human rubric/hint calibration and content approval. Patrick owns actual Splunk
ingestion, VM/environment validation and representative/range rehearsal evidence.
Ashley coordinates the client and schedule. Automated personas cannot establish
learner usability, assessor agreement, live ingestion/access controls or VM
snapshot restoration. The range's snapshot process remains the reset approach;
there is no reinstated 20-minute Ansible reset target.
