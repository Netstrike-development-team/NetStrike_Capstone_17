# NetStrike: Operation Silent Spider

**Capstone Project | SEG 4910 | University of Ottawa**  
Team: Ashley Goman, Anna Brimacombe-Tanner, Patrick Luu, Aya Debbagh  
Client: Dr. Miguel Garzon | Supervisors: Prof. Timothy Lethbridge, Prof. Garzon  
Partner: University of Ottawa Cyber Range

## What this is

Operation Silent Spider is a facilitated blue-team exercise for cybersecurity
students and junior defenders. Participants investigate a fictitious SimCorp
identity compromise that progresses through a Finance workstation, Active
Directory, a stateful Python mock cloud, and a safe impact/recovery stage.

The MVP is designed for one team in an isolated Cyber Range environment. It
uses synthetic identities and data, deterministic decision branches, Splunk
telemetry, and reversible actions. It does not use public-cloud resources,
real credential collection, learner-operated red teaming, or destructive
encryption.

## Exercise at a glance

- **Total duration:** 2 hours 50 minutes, including briefing and hotwash
- **Participants:** ideally 4; supported range 2–6
- **Learning goals:** triage, timeline reconstruction, containment, cloud
  scoping, recovery, and incident communication
- **Decision model:** four checkpoints select documented contained or adverse
  variants from verified exercise state
- **Delivery:** Cyber Range-managed amd64 VMs with no Internet access
- **Reset:** restore clean VM snapshots, then run readiness validation

## MVP technology

| Need | MVP choice |
|---|---|
| Scenario controller and portal | Python 3.11, FastAPI, SQLite, server-rendered web UI |
| SIEM | Cyber Range-provided Splunk Enterprise 10.0.1; capacity limits are recorded in the [CITEF decision log](docs/exercise-design/06-citef-requirements-and-approval.md) |
| Windows collection | Splunk Universal Forwarder 10.0.1, Sysmon 15.22, Windows audit and PowerShell logs |
| Endpoint response | NetStrike allowlisted safe actions; no commercial EDR dependency |
| Infrastructure configuration | Ansible over SSH/WinRM plus PowerShell where required |
| Cloud stage | Project-owned stateful Python mock; no AWS or LocalStack |
| Impact stage | Marker files and reversible moves inside disposable fixtures; no encryption |
| Offline installation | Staged and verified artifacts; see the [bundle status and installation guide](docs/deployment/offline-bundle.md) |

CALDERA, GHOSTS, Wazuh/Elastic, public cloud, and a custom SIEM are outside the
MVP. They may be reconsidered only after the complete blue-team exercise works.

## Repository structure

```text
dashboard/             Participant/facilitator portal and application services
orchestrator/           Scenario control, event handling, and action adapters
modules/                Scenario-stage implementations, fixtures, and safe actions
shared/                 Shared actions, event handling, and synthetic profiles
schemas/                Shared versioned event contracts and fixtures
splunk/                 Versioned Splunk apps, forwarder inputs, and checks
citef-config/           Infrastructure inventory, Ansible, and provisioning
scripts/                Offline bundle, provisioning, rehearsal, and validation tools
docs/README.md          Documentation index and task-based guide routes
docs/application/       Architecture, behavior, and versioned contracts
docs/deployment/        Offline build, provisioning, and release guidance
docs/development/       Roadmap, handoffs, and local rehearsals
docs/exercise-design/   Authoritative exercise design and delivery package
docs/operations/        Staff, participant, and evaluator workflows
_legacy/                Retired prototype code; not the maintained MVP path
licensed-installers/    Licensed deployment-artifact staging area
```

Some module names reflect the project's original attack-chain prototype; not
every module is an active exercise capability. The exercise-design package and
safe-action contracts define the supported MVP behavior, while `_legacy/`
contains retired implementations.

## Current state

The exercise design and shared event/safe-action contracts are in place, along
with safe identity, endpoint/AD, mock-cloud, and impact/recovery controls.
Offline Ansible provisioning and manifest validation are implemented. The
[November 1, 2026 local full-play validation](docs/deployment/offline-bundle-provisioning-validation.md)
records three consecutive restore/reprovision/readiness cycles; later evidence
documents Splunk source-health classification and alert triggering. These are
scoped local checks, not final exercise acceptance or proof of a later
deployment.

The offline bundle includes the portable Python runtime, resolved dependencies,
project source trees, pinned Ansible collections, and a generated per-artifact
inventory with checksums. CITEF deployment and complete clean-target exercise
acceptance remain open, as do external-artifact staging and manifest
verification, normalized portal-event forwarding, and end-to-end telemetry
acceptance.

See:

- [Documentation index](docs/README.md)
- [Exercise design package](docs/exercise-design/README.md)
- [Architecture](docs/application/architecture.md)
- [Roadmap and ownership](docs/development/roadmap.md)
- [Shared event contract](docs/application/contracts/event-contract-v1.md)
- [Safe-action contract](docs/application/contracts/safe-action-contract-v1.md)

## Full deployment

For a full exercise deployment, start with the
[full-play deployment runbook](docs/deployment/full-play-deployment-guide.md).
It links the required [offline bundle guide](docs/deployment/offline-bundle.md)
and [CITEF provisioning guide](citef-config/README.md), then covers provisioning,
readiness, live telemetry checks, and participant admission.

## Development workflow

- Feature branches and pull requests target `dev`.
- Normal merges require CI and at least one teammate review. #174 was an
  owner-authorized exception and did not claim independent review.
- Follow the [milestone promotion checklist](docs/deployment/milestone-release-checklist.md):
  `main` normally holds reviewed milestone/release snapshots. The October 14,
  2026 promotion (#174) is an explicitly validation-deferred development
  snapshot, not a tested milestone or accepted release. Post-merge CI passed;
  a separate downloadable rehearsal-artifact packaging issue is tracked in #175.
- Cyber Range-specific secrets and licensed installers are never committed.
