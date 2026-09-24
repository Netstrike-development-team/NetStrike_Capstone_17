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
| SIEM | Cyber Range-provided Splunk Enterprise |
| Windows collection | Splunk Universal Forwarder, Sysmon, Windows audit and PowerShell logs |
| Endpoint response | NetStrike allowlisted safe actions; no commercial EDR dependency |
| Infrastructure configuration | Ansible over SSH/WinRM plus PowerShell where required |
| Cloud stage | Project-owned stateful Python mock; no AWS or LocalStack |
| Impact stage | Marker files and reversible moves inside disposable fixtures; no encryption |
| Offline installation | Versioned Python wheelhouse, Ansible collections, installers, configs, and checksums pushed into the range |

CALDERA, GHOSTS, Wazuh/Elastic, public cloud, and a custom SIEM are outside the
MVP. They may be reconsidered only after the complete blue-team exercise works.

## Repository structure

```text
modules/              Controlled scenario fixtures and safe actions
orchestrator/          Scenario control, events, and action adapters
schemas/               Shared versioned event contracts
dashboard/             Existing participant/facilitator UI code
detection/             Existing detection and scoring code
citef-config/          Infrastructure and Ansible configuration
docs/exercise-design/  Authoritative exercise design and delivery package
docs/roadmap.md        Current schedule, ownership, and milestones
```

Some older module names remain because the project began as an attack-chain
prototype. The blue-team design package and safe-action contracts define the
supported MVP behavior.

## Current state

The exercise design, shared event contract, safe-action contract, and safe
identity, endpoint/AD, mock-cloud, and impact/recovery controls have been built
or are under review. The next delivery goal is a complete identity vertical
slice: start a run, deliver an inject, investigate it in Splunk, take a safe
containment action, score the checkpoint, export evidence, and restore the
environment.

See:

- [Exercise design package](docs/exercise-design/README.md)
- [Architecture](docs/architecture.md)
- [Roadmap and ownership](docs/roadmap.md)
- [Shared event contract](docs/event-contract-v1.md)
- [Safe-action contract](docs/safe-action-contract-v1.md)

## Development workflow

- Feature branches and pull requests target `dev`.
- CI and at least one teammate review are required before merge.
- `main` is reserved for tested milestone/release snapshots.
- Cyber Range-specific secrets and licensed installers are never committed.
