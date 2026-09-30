# Scenario controller

This package is the application-side control plane for Operation Silent Spider. It loads a reviewed, versioned MSEL, advances it deterministically, records every transition through the shared event contract, and exposes only explicitly registered automation handlers.

The first definition, `scenarios/identity-slice.v1.json`, covers setup through the DP2 contained/adverse branch. It supports:

- pre-exercise preparation;
- timed automatic injects and allowlisted actions;
- facilitator-delivered injects;
- pause, resume, inject-now, skip, fail-safe stop, and controller reset;
- evidence-backed checkpoint results and deterministic branch selection;
- an SIEM-independent DP1 evaluator for the identity, classification, artifact-count, and source-diversity requirements;
- canonical JSONL export plus a flattened CSV convenience export.

The controller does not execute arbitrary commands and does not contain Splunk credentials or server configuration. An automatic action runs only when its `action_id` has been registered with a handler. Missing or failed handlers leave the item visibly failed so the facilitator can use the documented evidence fallback.

## Development/Splunk boundary

The development side owns the scenario definition, controller behavior, safe action-handler interface, validated events, and exports. The environment/testing owner can ingest those events using a monitored JSONL file, Universal Forwarder, or HEC and can derive participant/evaluator searches from the same contract.

Splunk Enterprise installation, the dedicated index, role/access configuration, Universal Forwarder and HEC setup, Sysmon/add-ons, data-volume validation, and their Ansible automation remain environment work. Nothing in this package requires an Internet-connected exercise VM.

The CSV is for portability and facilitator review. JSONL remains the canonical source because it preserves nested safety, provenance, and event-specific evidence fields.

## Minimal use

```python
from pathlib import Path

from orchestrator import AutomationResult, ScenarioController, load_scenario

events = []
scenario = load_scenario(Path("orchestrator/scenarios/identity-slice.v1.json"))

def safe_handler(item, run_id):
    return AutomationResult(True, f"Completed {item.item_id}", {"run_id": run_id})

handlers = {
    item.action_id: safe_handler
    for item in scenario.items
    if item.action_id is not None
}
controller = ScenarioController(scenario, event_sink=events.append, handlers=handlers)
controller.prepare()
controller.start()
controller.advance_to(2400)
controller.resolve_checkpoint(
    "DP1",
    passed=True,
    evidence_ids=("identity-login-1", "helpdesk-ticket-1", "mfa-factor-1"),
    reason="Sarah identified with correlated identity and helpdesk evidence",
)
```
