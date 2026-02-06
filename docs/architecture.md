## 1. Overview
This project is a cloud/local cyber range platform allowing users to model an enterprise network, deploy it locally, run attacks, and observe detection systems.

## 2. Technology Stack

- **Backend:** Python + FastAPI
  - Orchestrates Vagrant, Ansible, Ghosts, Caldera, Wazuh
  - Provides REST API for frontend dashboard
- **Frontend:** React + TypeScript (planned)
  - Network builder UI
  - Attack timeline & SIEM dashboard visualization
- **Infrastructure:**
  - **Vagrant:** Creates reproducible VMs (DC, workstations, attacker, SIEM)
  - **Ansible:** Configures VMs, installs software/agents, joins domain
- **Attacks:** Caldera + Atomic Red Team
- **Background Traffic:** Ghosts
  - Simulates benign user behavior for realistic noise
- **SIEM:** Wazuh + Elastic dashboards
  - Collects telemetry, triggers alerts, visualizes IOCs

## 3. Development & Team Workflow

- **Branching Strategy**
  - `main` → production-ready
  - `dev` → integration branch
  - `feature/<task>` → individual task branches
- **Task Delegation**
  - Assign issues to team members
  - Tasks separated by backend, frontend, infra, attacks, SIEM, Ghosts
- **PR/MR Workflow**
  - Open PR from feature -> dev
  - At least 2 reviewer approval required
  - Merge only after CI passes
- **Sprints**
  - 1–2 week sprints
  - Use GitHub Projects 
  - Standups: 10–15 min check-ins

## 4. CI/CD (Phase 1)
- Backend: lint + pytest + coverage
- Frontend (later): TypeScript lint + build
- Optional security scan with bandit

## 5. Commit Naming / Conventions

All commits should follow a structured format:
**Types and when to use them:**
- feat: New feature `feat(vagrant): add DC VM skeleton`
- fix: Bug fix `fix(ansible): correct Wazuh agent path`
- chore: Repo / tooling `chore: create initial repo structure`
- docs: Documentation `docs(architecture): add Ghosts integration`
- style: Formatting / lint `style: format Python files`
- refactor: Code restructure `refactor(backend): reorganize services folder`
- test: Add/update tests `test: add pytest for Vagrant service`
- perf: Performance improvement `perf(ansible): optimize DC provisioning`

## 6. Reasoning for Choices
- Python: Best for orchestration, integrates with all security frameworks, fast dev
- Vagrant: Local-first, reproducible VM environments, resettable for attacks
- Ansible: Configures machines automatically (AD, agents, Ghosts)
- Ghosts: Adds realistic benign user traffic for detection testing
- React: Planned frontend for visualization and network builder UI

## 7. Collaboration Principles
- Keep tasks small and assignable
- Work in feature branches only
- Merge to `dev` for integration, then to `main`
- Document APIs and interfaces early for frontend/backend separation
