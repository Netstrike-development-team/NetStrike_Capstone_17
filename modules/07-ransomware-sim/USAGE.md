# Marker-impact usage

The Silent Spider MVP supports marker mode only. Do not add real encryption,
VM-disk access, backup deletion, or vCenter connectivity.

## Exercise integration

The controller creates a new run-specific fixture beneath a Cyber
Range-approved absolute directory, then registers the adapter:

```python
from impact_actions import ImpactFixture, build_impact_adapter

fixture = ImpactFixture.provision("/approved/netstrike-runs", "run-001")
adapter = build_impact_adapter(
    exercise_id="silent-spider",
    run_id="run-001",
    fixture=fixture,
    run_state=current_run_state,
    event_sink=event_ledger.append,
)
```

The approved API actions are:

- `impact.marker.apply` with `{"variant": "blocked"}` or
  `{"variant": "realized"}`;
- `recovery.fixture.restore`;
- `recovery.health.validate`;
- `exercise.impact.reset`; and
- `exercise.impact.readiness.validate`.

Requests must be built through `shared.actions.make_action_request`. Never call
fixture mutation methods from a portal or scenario route directly.

## Branch behavior

The blocked branch adds five harmless marker companions and leaves originals
in place. The realized branch moves only the five allowlisted disposable files
to controller-managed staging, then creates marker companions and an
exercise-only note. Recovery copies the verified known-good data back and
removes markers, the note, and staged originals.

Every filesystem path comes from the provisioned fixture. Action requests do
not accept paths, filenames, encryption modes, keys, or arbitrary content.

## Legacy demonstration

`python main.py --standalone --test-dir <new-disposable-directory>` remains for
local demonstration of generated fake files. It supports `mode: marker` only,
does not modify the generated originals, and is not used by the exercise
controller.

## Verification

```bash
python -m pytest modules/07-ransomware-sim/tests shared/tests -q
```
