# CI test results and coverage evidence

The module workflow previously ignored pytest failures and wrote nested-module
coverage under `modules/` while uploading from the repository root. It also used
slash-containing artifact names and attempted uploads for modules without tests.
Those are repository defects, distinct from GitHub failing to assign a hosted
runner. This change fixes the defects; it cannot repair GitHub's service.

## What now blocks a merge

`Lint and Test` retains `event-contract` and the ten `module-checks (...)` job
identities. It runs on PRs targeting main/dev and pushes to main/dev, avoiding
duplicate feature-push runs and covering the maintained integration branches.
Shared contract tests stay strict. Module jobs now return failed pytest or
collection exit codes instead of swallowing them. Text and HTML coverage are
attempted after tests even if they failed; passing coverage cannot turn failed
tests into success. Failed coverage generation also blocks a passing test job.
No numeric minimum coverage threshold or full security coverage is implied.

Each module detects its tests directory explicitly. A missing directory means
no test run or coverage upload and is labelled **not test validation**. A present
but empty/broken suite fails through pytest. Module lint remains informational;
the separate maintained-code security and strict core/full-play checks are still
required. Legacy test success is not permission to use legacy attack entry points.

Reports use absolute `$RUNNER_TEMP/module-coverage/MODULE_NAME` paths, independently
of module working directories. Artifacts are `coverage-txt-MODULE_NAME` and
`coverage-html-MODULE_NAME`, without slashes. Uploads run after failures only for
modules with tests; missing expected reports are errors, not silent success.
Reports are retained for 14 days. No artifact is promised if collection/runtime
failure prevents its creation. Preserve relevant evidence before expiry.

Module jobs have a 15-minute bound, three-way maximum parallelism and
`fail-fast: false`, so one failed module does not cancel its siblings. Contract
jobs have a five-minute bound. These settings reduce bursts/cascading cancellation
but do not guarantee hosted-runner availability during an outage.

## Runner/action maintenance

All four workflows use `ubuntu-24.04` and immutable official Node-24-compatible
v6 action commits verified on October 5:

| Action | Pinned commit |
| --- | --- |
| [checkout](https://github.com/actions/checkout/tree/d23441a48e516b6c34aea4fa41551a30e30af803) | `d23441a48e516b6c34aea4fa41551a30e30af803` |
| [setup-python](https://github.com/actions/setup-python/tree/ece7cb06caefa5fff74198d8649806c4678c61a1) | `ece7cb06caefa5fff74198d8649806c4678c61a1` |
| [setup-node](https://github.com/actions/setup-node/tree/249970729cb0ef3589644e2896645e5dc5ba9c38) | `249970729cb0ef3589644e2896645e5dc5ba9c38` |
| [upload-artifact](https://github.com/actions/upload-artifact/tree/b7c566a772e6b6bfb58ed0dc250532a479d7789f) | `b7c566a772e6b6bfb58ed0dc250532a479d7789f` |

This avoids Node-20 action deprecation and the moving Ubuntu image notice without
taking the newer v7 interface/archive changes. The action runtime is **not** the
application test runtime: core tests still use Python 3.11 and Node 22. Offline
bundle destination, portable Python version/build, download/build/verify commands
and manual dispatch remain unchanged; no bundle is built or dispatched by this
PR. A CI image pin is not a change to Patrick's range VM topology or install plan.

All workflows have read-only repository permissions. Checkout does not persist
credentials; dependency-free Node tests explicitly disable automatic package
manager caching. Official v6 actions require a recent Actions runner (at least
2.327.1; checkout's authenticated Docker-container Git use needs 2.329.0). There
is no self-hosted runner setup or network-isolation claim. Pins must be reviewed
when updating, not replaced with unverified hashes or insecure Node opt-outs.

## Regression evidence and limits

`scripts/tests/test_module_ci_workflow.py` parses the workflow and executes its
actual shell with task-local fake coverage tooling to check success, pytest
failure/collection codes and report-generation errors. It also runs a real
tiny passing/failing pytest suite under coverage, checking both text and HTML
output. Test fixtures are disposable and make no external requests. Existing
PyYAML validator and CI coverage dependencies are reused; no application runtime
dependency is added. Tests inspect matrix identity, report paths, conditions,
permissions, pins, runtime versions and no-tests boundaries.

The first strict dashboard run exposed a previously masked archive test failure:
its cloud fixture path assumed the repository-root working directory. The test
now resolves the fixture from its own file and deliberately runs from a disposable
non-repository directory, while retaining all persistence/no-resume assertions.
No application scenario-path semantics or archive behavior changed.

The full core/Node/24-case regression workflow remains strict. Source fingerprints
now include all four workflow files. Workflow tests alone do not prove hosted
actions executed; actual run URLs/results must be retained. A skipped **step**
because a module has no tests is different from a cancelled **job** that never
acquired a runner. Neither means nonexistent tests passed.

See [maintained security scope](application-security-gate.md) and
[milestone promotion](milestone-release-checklist.md). PR #152's one-time
outage/review exception does not authorize exceptions for later PRs; #153 remains
open for actual retrospective teammate review even though its post-merge CI passed.
