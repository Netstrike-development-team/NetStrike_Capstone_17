# NetStrike: Project Roadmap

**Capstone:** SEG 4910 | University of Ottawa  
**Team:** Ashley Goman, Anna Brimacombe-Tanner, Patrick Luu, Aya Debbagh  
**Partner:** University of Ottawa Cyber Range

---

## Project Goal

Build a modular, portable attack simulation suite that models the **Scattered Spider
(UNC3944)** kill chain inside the CITEF cyber range, with a detection and evaluation
framework. Deliver reusable scenario artifacts that the Cyber Range team can integrate
into their next-generation platform.

---

## Milestones

### Milestone 1: Foundation (Week 1-2)
**Goal:** Repo structured, schemas defined, first module working, team unblocked to
build in parallel.

- [x] Restructure repo to match scenario design document
- [x] Archive legacy code to `_legacy/`
- [x] Write new README reflecting current project
- [ ] Define and commit `schemas/event.json`
- [ ] Define and commit `schemas/target_profile.json`
- [ ] Build `modules/01-osint-profiler/`: employee DB + profiler + tests
- [ ] Commit `orchestrator/run.py` stub that sequences all 7 phases
- [ ] Update architecture.md and roadmap.md
- [ ] Triage and close legacy GitHub Issues

---

### Milestone 2: Core Social Engineering Modules (Week 2-3)
**Goal:** Phases 1-4 fully implemented and testable locally with no infrastructure.

- [ ] `modules/02-phishing-infra/`: Flask fake Okta page + credential capture backend
- [ ] `modules/03-vishing-scripts/`: Jinja2 script generator from OSINT profile
- [ ] `modules/04-mfa-fatigue-sim/`: mock Okta push API + flooding simulator
- [ ] Unit tests for modules 01-04 (`pytest` + coverage > 70%)
- [ ] CI passing on `dev` branch for all modules

---

### Milestone 3: Infrastructure Modules (Week 3-4)
**Goal:** Phases 5-7 implemented against local mocks (VirtualBox AD + LocalStack).

- [ ] `modules/05-lateral-movement/`: AD enumeration + Pass-the-Hash simulation
- [ ] `modules/06-cloud-exfil/`: LocalStack S3 enumeration + bulk download
- [ ] `modules/07-ransomware-sim/`: benign AES encryptor + RansomHub note format
- [ ] `citef-config/localstack/seed_s3.py`: synthetic PII dataset generator
- [ ] Unit tests for modules 05-07

---

### Milestone 4: Orchestrator + CALDERA Integration (Week 4-5)
**Goal:** Full scenario runs end-to-end with one command.

- [ ] `orchestrator/run.py`: complete scenario runner (not stub)
- [ ] `orchestrator/caldera_client.py`: finalized Caldera API integration
- [ ] `citef-config/caldera/scattered_spider.yaml`: Scattered Spider adversary profile
- [ ] `orchestrator/flag_tracker.py`: tracks all 7 flags with timestamps
- [ ] `orchestrator/event_logger.py`: writes `scenario_events.jsonl`
- [ ] Orchestrator REST API (`POST /start`, `GET /status`, `POST /stop`)
- [ ] Integration test: full scenario run produces expected flags + events

---

### Milestone 5: Detection Layer (Week 5-6)
**Goal:** Log analyzer scores a complete scenario run, dashboard shows results.

- [ ] `detection/log_analyzer.py`: 20 detection rules (one per ATT&CK technique)
- [ ] `detection/scoring.py`: computes 5 evaluation metrics
- [ ] `detection/alerts.jsonl` schema defined
- [ ] `dashboard/` backend: FastAPI serving alerts + events as REST API
- [ ] `dashboard/` frontend: React UI with:
  - [ ] Real-time event feed
  - [ ] MITRE ATT&CK heatmap (detected vs. missed)
  - [ ] Per-phase detection scores
  - [ ] Attack timeline view
- [ ] Dashboard loads from pre-recorded scenario logs (demo mode)

---

### Milestone 6 Full Environment + GHOSTS (Week 6-7)
**Goal:** Complete Vagrant environment runs scenario end-to-end, GHOSTS provides
realistic baseline traffic.

- [ ] `citef-config/Vagrantfile`: all 6 VMs defined
- [ ] `citef-config/ansible/dc.yml`: domain controller setup
- [ ] `citef-config/ansible/users.yml`: 20 domain users from OSINT DB
- [ ] `citef-config/ansible/workstation.yml`: agents + weak configs
- [ ] `citef-config/ansible/siem.yml`: Wazuh + Elastic
- [ ] `ghosts/timelines/`: activity profiles for 3 SimCorp employees
- [ ] End-to-end test: `vagrant up` → `python orchestrator/run.py` → dashboard

---

### Milestone 7: CITEF Deployment + Demo Prep (Week 7-8)
**Goal:** Scenario runs on actual CITEF cyber range, ready for capstone demo.

- [ ] `citef-config/citef.yaml`: CITEF-specific environment config
- [ ] Deploy and test against CITEF environment with Cyber Range team
- [ ] Record scenario execution for demo backup (in case of live environment issues)
- [ ] Portability report: document what changed between local and CITEF deployment
- [ ] Final README cleanup
- [ ] Tag `v1.0` release

---

## Current Status

| Component | Status |
|-----------|--------|
| Repo structure | ✅ Done |
| README | ✅ Done |
| Architecture docs | ✅ Done |
| Schemas | 🔄 In progress |
| Module 01 (OSINT) | 🔄 In progress |
| Modules 02-07 | ⬜ Not started |
| Orchestrator | 🔄 Stub exists |
| Detection layer | ⬜ Not started |
| Dashboard | ⬜ Not started |
| Vagrant/Ansible | ⬜ Not started |
| CITEF deployment | ⬜ Pending range access |

---

## How We Work

- **Sprints:** 1-week sprints, milestone-aligned
- **Standups:** 2x per week, 15 min
- **Branches:** `feature/<module-name>` → PR to `dev` → merge to `main` at milestone
- **PRs:** minimum 1 reviewer, CI must pass
- **Issues:** one GitHub Issue per checklist item above, labeled by module