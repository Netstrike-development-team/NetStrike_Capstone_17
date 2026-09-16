# NetStrike — Architecture

## 1. Overview

NetStrike is a modular attack simulation suite modelling **Scattered Spider (UNC3944)**, a
financially motivated threat actor group. The project executes a full 7-phase kill chain inside
the CITEF cyber range environment, from OSINT reconnaissance through to ransomware
deployment, with a real-time detection dashboard and MITRE ATT&CK-tagged event logging.

The architecture is designed around two principles:

- **Modularity** — each attack phase is an independent, runnable module with its own
  config, tests, and event output. Modules can be developed and tested locally without
  the full CITEF environment.
- **Portability** — all environment-specific parameters (hostnames, credentials, IPs) live
  in YAML config files. Swapping `local.yaml` for `citef.yaml` retargets the entire suite
  with no code changes.

---

## 2. System Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│  run.py  ─►  CalderaClient  ─►  CALDERA (C2 framework)  │
│           ─►  FlagTracker                               │
│           ─►  EventLogger  ─►  scenario_events.jsonl    │
└────────────────────────┬────────────────────────────────┘
                         │ triggers
         ┌───────────────┼───────────────┐
         ▼               ▼               ▼
   ATTACK MODULES    GHOSTS (victims)  CITEF ENVIRONMENT
   01 osint          SimCorp employees  Windows AD domain
   02 phishing       browsing, emailing VMware ESXi
   03 vishing        approving pushes   Okta SSO (simulated)
   04 mfa-fatigue                       AWS / LocalStack
   05 lateral-move                      Wazuh SIEM
   06 cloud-exfil
   07 ransomware-sim
         │
         ▼
   DETECTION LAYER
   LogAnalyzer  ─►  MITRE-tagged alerts
   Dashboard    ─►  React UI (real-time)
```

---

## 3. Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Attack orchestration | Python 3.11 + FastAPI | Sequences modules, calls Caldera API, tracks flags |
| Adversary emulation | MITRE CALDERA | Executes ATT&CK techniques on range agents |
| Victim simulation | NIST GHOSTS | Simulates benign employee behaviour (browsing, email) |
| SIEM / detection | Wazuh + Elastic | Collects host telemetry, triggers alerts, surfaces IOCs |
| Infrastructure | Vagrant + Ansible | Provisions and configures all VMs reproducibly |
| Dashboard frontend | React + TypeScript | Real-time attack timeline, MITRE heatmap, scoring |
| Dashboard backend | FastAPI | Serves log analyzer output as REST API |
| Event schema | Versioned NetStrike JSON Schema | Shared contract between modules, control, Splunk, evaluation, reset, and AAR |
| Local cloud mock | LocalStack | Simulates AWS S3 for cloud exfil module (no real AWS) |

---

## 4. Module Architecture

Each module under `modules/` follows the same structure:

```
modules/XX-module-name/
├── README.md          # What it does, how to run, example output
├── main.py            # Entry point — callable by orchestrator
├── config.yaml        # Module-specific defaults
├── requirements.txt   # Module-level dependencies
└── tests/
    └── test_main.py
```

Every module's `main.py` exposes a `run(config: dict) -> list[Event]` function.
The orchestrator calls this function, collects the returned events, and writes them
to `scenario_events.jsonl` in the shared event schema.

### Shared Event Schema (`schemas/event.v1.json`)

The authoritative contract, migration rules, producer/consumer requirements,
and CITEF-neutral Splunk mappings are documented in
[`docs/event-contract-v1.md`](event-contract-v1.md). `schemas/event.json`
remains the stable compatibility entry point.

All state-changing operations additionally pass through the
[`Safe Action Adapter Contract v1`](safe-action-contract-v1.md), which enforces
role, run-state, allowlist, timeout, idempotency, dry-run, fail-safe, audit, and
rollback policy before invoking a module handler.

Every producer emits validated, run-correlated events in this shape:

```json
{
  "schema_version": "1.0.0",
  "event_id": "11111111-1111-4111-8111-111111111111",
  "timestamp": "2026-09-16T14:00:00.000Z",
  "exercise_id": "silent-spider",
  "run_id": "run-20260916-001",
  "sequence": 1,
  "event_type": "recon.source.harvested",
  "phase": "reconnaissance",
  "source": {"kind": "module", "component": "01-osint-profiler"},
  "actor": {"type": "system", "id": "01-osint-profiler"},
  "action": "source.harvest",
  "target": {"type": "dataset", "id": "simcorp-employees"},
  "outcome": {"status": "success"},
  "severity": "info",
  "visibility": "facilitator",
  "safety": {
    "simulation_only": true,
    "dry_run": false,
    "within_allowlist": true,
    "destructive": false
  },
  "provenance": {"producer": "01-osint-profiler", "producer_version": "1.0.0"},
  "message": "Harvested five synthetic SimCorp employee records",
  "data": {"record_count": 5, "synthetic": true}
}
```

---

## 5. Orchestrator

`orchestrator/run.py` is the top-level scenario runner. It:

1. Loads the environment config (`--config citef-config/local.yaml` or `citef.yaml`)
2. Instantiates `CalderaClient` and verifies connectivity
3. Calls each module's `run()` function in sequence
4. Writes all returned events to `scenario_events.jsonl`
5. Tracks flag state in `flags.json`
6. Exposes a REST API (`POST /start`, `GET /status`, `POST /stop`) for integration
   with the Cyber Range team's exercise management system

---

## 6. CALDERA Integration

CALDERA serves as the execution engine for phases that require agent-side technique
execution (phases 5, 6, 7). Our `orchestrator/caldera_client.py` wraps the CALDERA
REST API and handles:

- Creating operations with the Scattered Spider adversary profile
- Polling operation status until completion
- Retrieving ability results and translating them into our event schema

The Scattered Spider adversary profile (`citef-config/caldera/scattered_spider.yaml`)
chains the relevant ATT&CK abilities in kill chain order.

Phases 1-4 (OSINT, phishing, vishing, MFA fatigue) run as standalone Python modules
because CALDERA has no concept of social engineering or pre-access reconnaissance.

---

## 7. Detection Layer

```
scenario_events.jsonl
        │
        ▼
detection/log_analyzer.py
  ├── Applies 20 detection rules (one per MITRE technique)
  ├── Each rule: pattern match on event fields → Alert object
  └── Scoring engine computes:
        - Detection Rate per phase
        - False Positive Rate
        - Time-to-Detect (TTD)
        - MITRE Coverage Score
        - Portability Score
        │
        ▼
detection/alerts.jsonl  ──►  Dashboard FastAPI backend  ──►  React UI
```

---

## 8. Infrastructure (Vagrant + Ansible)

Vagrant provisions the SimCorp environment:

| VM | OS | Role |
|----|-----|------|
| `dc01` | Windows Server 2019 | Active Directory Domain Controller |
| `ws01`, `ws02`, `ws03` | Windows 10 | Employee workstations |
| `attacker` | Kali Linux | Red team attack machine |
| `siem` | Ubuntu 22.04 | Wazuh + Elastic SIEM |

Ansible configures each VM after provisioning:
- Promotes `dc01` to domain controller, creates SimCorp domain
- Creates 20 domain users matching the OSINT profiler employee database
- Joins workstations to the domain
- Installs Wazuh agents, Sysmon, and GHOSTS agents on workstations
- Configures intentionally weak settings to support attack chain
- Pre-populates LocalStack S3 with synthetic PII dataset

---

## 9. Development Workflow

### Branching

```
main       ← production-ready, protected
  └── dev  ← integration branch
        └── feature/<module-name>  ← individual work
```

### PR Rules

- Open PR from `feature/*` → `dev`
- Minimum 1 reviewer approval required
- CI must pass (lint + pytest + coverage)
- Merge `dev` → `main` at end of each sprint milestone

### Commit Convention

```
feat(module):    new feature         feat(osint): add email pattern extractor
fix(module):     bug fix             fix(mfa-sim): correct push interval timing
chore:           tooling/repo        chore: add pre-commit hooks
docs(module):    documentation       docs(architecture): update system diagram
test(module):    tests               test(phishing): add credential capture tests
refactor:        restructure         refactor(orchestrator): extract flag tracker
```

### CI/CD (GitHub Actions)

- **Python:** `flake8` lint + `pytest` + coverage report
- **Frontend:** TypeScript lint + `npm run build`
- **Security:** `bandit` static analysis on all Python modules
- Runs on every push to `dev` and every PR

---

## 10. Local Development (No CITEF Needed)

All modules can be developed and tested locally:

| Module | Local substitute |
|--------|-----------------|
| Active Directory (phases 5) | VirtualBox VM with Windows Server eval |
| AWS S3 (phase 6) | LocalStack (`pip install localstack`) |
| Okta SSO (phase 4) | Mock Flask API in `modules/04-mfa-fatigue-sim/mock_okta.py` |
| CALDERA (phases 5-7) | CALDERA runs locally via Docker |
| Full environment | `vagrant up` in `citef-config/` |

One-command local setup:

```bash
pip install -r requirements.txt
python orchestrator/run.py --config citef-config/local.yaml
```
