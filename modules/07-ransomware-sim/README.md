# Module 7: Marker impact and recovery

## Purpose

This module implements the marker-only impact and recovery phase of Operation
Silent Spider. The MVP does not encrypt files, access VM disks, disable real
backups, or connect to vCenter.

- `impact_actions.py` is the authoritative exercise-control surface. It is
  confined to one approved, run-specific disposable directory and is invoked
  only through the shared safe-action adapter.
- `main.py` is a legacy event/marker demonstration. It may create companions
  beside files it generated itself, but it is not an exercise-state authority.
- The former AES encryption utility and decryption CLI have been removed.

## Disposable fixture

`ImpactFixture.provision(approved_root, run_id)` creates this layout without
overwriting an existing run:

```text
<approved-root>/<run-id>/
├── live/        # five synthetic canary files
├── known-good/  # immutable recovery copies
└── staging/     # controller-managed unavailable originals
```

The fixture has five exact filenames and an expected SHA-256 manifest embedded
in code. The implementation rejects relative roots, unsafe run IDs, symlinks,
unexpected files or directories, escaped paths, and modified known-good data.
No action accepts a caller-provided filesystem path.

## Registered safe actions

| Action | Role | State | Effect |
| --- | --- | --- | --- |
| `impact.marker.apply` | `scenario_engine` or `facilitator` | `running` | executes the approved `blocked` or `realized` marker branch |
| `recovery.fixture.restore` | `cloud_responder` or `facilitator` | `running` | restores live files from known-good copies and removes impact artifacts |
| `recovery.health.validate` | recovery/control roles | active or recovery states | validates exact inventories and hashes |
| `exercise.impact.reset` | `technical_operator` or `facilitator` | `stopped` or `resetting` | restores the baseline fixture |
| `exercise.impact.readiness.validate` | `technical_operator` or `facilitator` | setup/recovery states | gates the next run on a clean fixture |

All participant/engine actions target only
`fixture_set:FILE01-disposable-fixture`.

### Blocked branch

Five harmless `.NETSTRIKE-MARKER` companions are created. All originals remain
available and byte-for-byte unchanged. No exercise note is written.

### Realized branch

The five disposable originals move to the run's `staging/` directory. Marker
companions and an exercise-only note are created in `live/`. The note explicitly
states that no encryption occurred. Before/after manifests are retained in the
fixture report, and the originals remain recoverable by the controller.

## Failure and recovery behavior

Each mutation captures an exact filesystem snapshot. Injected or real partial
write failures trigger immediate restoration before the adapter returns a safe
failure code. Successful operations expose a one-use facilitator rollback.
Idempotency prevents the same request from running twice, while a new impact
request against a dirty fixture fails as `fixture_not_ready`.

The shared adapter additionally enforces correlation, role, target, run state,
parameters, timeout, dry-run, cancellation, event validation, and auditing.

## Development

From the repository root:

```bash
python -m pip install -r modules/07-ransomware-sim/requirements.txt
python -m pytest modules/07-ransomware-sim/tests shared/tests -q
```

The focused tests include both MSEL branches, unchanged originals, exposure
artifacts, traversal and symlink denial, target/role denial, dry-run,
idempotency, partial-failure rollback, recovery, reset, readiness, manifests,
and shared event validation.
