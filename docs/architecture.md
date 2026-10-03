# NetStrike Blue-Team MVP Architecture

## Purpose

NetStrike delivers Operation Silent Spider as one safe, facilitated blue-team
exercise. The system schedules a fixed scenario, records what happens, exposes
approved investigation and response actions, sends evidence to Splunk, and
supports evaluation and after-action review.

## Logical architecture

```text
Participant/facilitator browser
              |
              v
      CTRL01 controller + portal
      - run and MSEL state
      - event ledger
      - checkpoints/scoring
      - safe-action adapters
        |        |         |
        v        v         v
      IDP/     FIN-WS01/   CLOUD01/FILE01
    Helpdesk      DC01     Python mock + fixtures
        \          |          /
         \---------+---------/
                   |
                   v
                SPLUNK01
```

Logical services may share VMs. The minimum useful topology keeps the domain
controller, participant workstation, Splunk, and controller outside one
another's failure boundaries. The team will map these assets to Cyber Range
amd64 VMs and may consolidate project-owned Linux services.

## Main components

### Controller and portal

Python 3.11 and FastAPI provide the API, server-rendered participant and
facilitator pages, and authenticated action endpoints. SQLite is sufficient
for the single-team MVP event ledger. The controller owns run state, MSEL
timing, checkpoint evaluation, hints, fallbacks, emergency stop, and exports.

### Safe actions

Every state-changing operation uses the versioned safe-action adapter. It
checks the caller role, exercise state, target allowlist, timeout,
idempotency, and rollback information before a handler runs. The MVP supports
safe identity, endpoint/AD, mock-cloud, and marker-impact/recovery actions.

### Telemetry and Splunk

Windows VMs emit native audit, PowerShell, and Sysmon events through the
Splunk Universal Forwarder. Project-owned services send normalized NetStrike
events through a confirmed Splunk input, preferably HEC. Splunk is the only
SIEM in the MVP.

No commercial EDR is required. Sysmon provides endpoint activity telemetry;
NetStrike's allowlisted action adapters provide the exercise containment
controls. Staff and learner material must not describe this as a production
EDR deployment.

### Infrastructure

The team designs the topology in the Cyber Range platform. Ansible configures
DNS, NTP, Windows/AD policy, services, telemetry, fixtures, and health checks
using SSH or WinRM. The range has no Internet access, so all required packages,
collections, installers, and configuration are transferred as a reviewed,
versioned offline bundle.

Clean Cyber Range snapshots are the primary restoration mechanism. Ansible is
used for initial provisioning and readiness validation, not as a replacement
for snapshots or as a timed full reset mechanism.

## Delivery VM baseline

| Logical asset | Proposed platform | Responsibility |
|---|---|---|
| `CTRL01` | Linux | Controller, portal, ledger, mock IdP/helpdesk/cloud services |
| `DC01` | Windows Server | SimCorp Active Directory and directory audit evidence |
| `FIN-WS01` | Windows 11 | Participant investigation and endpoint scenario state |
| `SPLUNK01` | Supported Linux or Cyber Range image | Splunk Enterprise and exercise content |
| `FILE01` | On `CTRL01` or a small Linux VM | Disposable impact fixtures and known-good copy |

The final VM count, images, resources, network, and access model are captured
as environment configuration rather than hard-coded in application logic.

## Explicitly out of scope for the MVP

- A commercial EDR or Microsoft Defender for Endpoint dependency
- Wazuh/Elastic as a second SIEM
- CALDERA or an open-ended autonomous attacker
- GHOSTS background-traffic simulation
- LocalStack or public-cloud accounts
- Learner-operated red teaming
- Real encryption, disk modification, or Internet-connected targeting

## Source of truth

- Event format: [event-contract-v1.md](event-contract-v1.md)
- Action safety: [safe-action-contract-v1.md](safe-action-contract-v1.md)
- Exercise behavior: [exercise-design/02-storyline-and-msel.md](exercise-design/02-storyline-and-msel.md)
- Telemetry: [exercise-design/03-telemetry-evidence-matrix.md](exercise-design/03-telemetry-evidence-matrix.md)
- Tools/offline plan: [exercise-design/07-offline-tool-bundle-inventory.md](exercise-design/07-offline-tool-bundle-inventory.md)
