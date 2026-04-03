# NetStrike: Operation Silent Spider

**Capstone Project | SEG 4910 | University of Ottawa**  
Team: Ashley Goman, Anna Brimacombe-Tanner, Patrick Luu, Aya Debbagh  
Client: Dr. Miguel Garzon | Supervisors: Prof. Timothy Lethbridge, Prof. Garzon  
Partner: University of Ottawa Cyber Range

---

## What This Is

A modular attack simulation suite modeling **Scattered Spider (UNC3944)**,
one of the most active financially motivated threat actor groups operating today.
The suite executes a full 7-phase kill chain within the CITEF cyber range,
from OSINT reconnaissance through to ransomware deployment, with a real-time
detection dashboard and MITRE ATT&CK-tagged event logging.

Built to run in CITEF today and portable to the Cyber Range team's
next-generation platform.

---

## Attack Phases

| Module | Phase | Description |
|--------|-------|-------------|
| `01-osint-profiler` | Reconnaissance | OSINT scraper building structured target profiles |
| `02-phishing-infra` | Initial Access | Fake Okta login page + credential capture backend |
| `03-vishing-scripts` | Identity Takeover | Context-aware helpdesk impersonation script generator |
| `04-mfa-fatigue-sim` | MFA Bypass | Push bombing simulator against simulated Okta |
| `05-lateral-movement` | Lateral Movement | AD enumeration + privilege escalation engine |
| `06-cloud-exfil` | Data Exfiltration | S3 enumeration + bulk data download via AWS CLI |
| `07-ransomware-sim` | Impact | Benign AES file encryptor mimicking RansomHub |

All phases are executed via **MITRE CALDERA** (adversary emulation framework)
and orchestrated by our custom Python scenario runner.

---

## Detection Layer

- **Log Analyzer**: ingests structured JSON events from all modules, applies
  MITRE ATT&CK-mapped detection rules, scores each phase
- **Detection Dashboard**: real-time React UI showing attack timeline,
  technique heatmap, and blue team scoring
- **SIEM Integration**: Wazuh collects host telemetry; dashboards surface
  IOCs and lateral movement paths

---

## Stack

| Component | Technology |
|-----------|------------|
| Attack orchestration | Python + FastAPI + CALDERA API |
| Victim simulation | GHOSTS (NIST) |
| Detection / SIEM | Wazuh + Elastic |
| Local infrastructure | Vagrant + Ansible |
| Dashboard | React + TypeScript + FastAPI |
| Event schema | STIX 2.1-aligned JSON |

---

## Repository Structure
```
NetStrike_Capstone_17/
├── _legacy/                    # Pre-pivot code (archived)
│   ├── attacks/
│   ├── backend/
│   ├── frontend/
│   ├── infrastructure_old/
│   └── SIEM/
├── modules/
│   ├── 01-osint-profiler/      # Reconnaissance: OSINT automation
│   ├── 02-phishing-infra/      # Initial Access: credential capture page
│   ├── 03-vishing-scripts/     # Identity Takeover: call script generator
│   ├── 04-mfa-fatigue-sim/     # MFA Bypass: push bombing simulator
│   ├── 05-lateral-movement/    # Lateral Movement: AD enumeration engine
│   ├── 06-cloud-exfil/         # Exfiltration: S3 data theft module
│   └── 07-ransomware-sim/      # Impact: benign AES encryption payload
├── orchestrator/               # Scenario runner, Caldera client, flag tracker
├── detection/                  # Log analyzer, MITRE detection rules, scoring
├── dashboard/                  # React frontend + FastAPI backend
├── ghosts/                     # NIST Ghosts victim simulation config
├── citef-config/               # Vagrant + Ansible environment setup
├── schemas/                    # Shared JSON schemas
├── docs/                       # Scenario design document + references
└── scripts/                    # Utility scripts
```

---

## Scenario Design Document

See [`docs/operation-silent-spider.pdf`](docs/operation-silent-spider.pdf)
for the full scenario design including MITRE ATT&CK mappings, exercise
timeline, and CITEF environment requirements.

---

## MITRE ATT&CK Coverage

14 tactic categories | 20+ techniques mapped  
Full mapping in scenario document and tagged on every emitted log event.