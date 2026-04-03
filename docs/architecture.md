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
| Event schema | STIX 2.1-aligned JSON | Shared contract between all modules and detection layer |
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

### Shared Event Schema (`schemas/event.json`)

Every module emits events in this format:

```json
{
  "event_id": "uuid",
  "timestamp": "2026-04-03T12:00:00Z",
  "phase": 1,
  "technique_id": "T1593.001",
  "tactic": "reconnaissance",
  "description": "OSINT profile built for Sarah Mitchell (VP Finance)",
  "source_module": "01-osint-profiler",
  "flag_triggered": "FLAG_1_RECON_COMPLETE",
  "raw_data": {}
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