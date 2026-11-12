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

The configured deployment path uses Splunk Universal Forwarder inputs for native Windows audit,
PowerShell, and Sysmon events and for the application-event spools. The
canonical ledger goes to the staff-only index; a separate reviewed projection
goes to the learner index. The Ansible and Splunk configuration is implemented,
but live delivery, access boundaries, and source health must be verified for
the selected deployment. See the [spool guide](event-spool.md), the
[learner audit guide](../operations/learner-splunk-audit.md), and the
[Windows TLS limitation](../deployment/splunk-sysmon-ingest.md#receiver-prerequisites).
Splunk is the only SIEM in the MVP.

No commercial EDR is required. Sysmon provides endpoint activity telemetry;
NetStrike's allowlisted action adapters provide the exercise containment
controls. Staff and learner material must not describe this as a production
EDR deployment.

### Infrastructure

The team designs the topology in the Cyber Range platform. Ansible configures
DNS, NTP, Windows/AD policy, services, telemetry, fixtures, and health checks
using SSH or WinRM. Scenario VMs have no Internet access, so all required
packages, collections, installers, and configuration are transferred as a
reviewed, versioned offline bundle.

Clean Cyber Range snapshots are the primary restoration mechanism. Ansible is
used for initial provisioning and readiness validation, not as a replacement
for snapshots or as a timed full reset mechanism.

The final VM count, image versions, resources, network, and access model are
captured as environment configuration rather than hard-coded in application
logic. The proposed logical mapping, fail-closed inventory, Ansible procedure,
and external readiness workflow are documented in
[`citef-config/README.md`](../../citef-config/README.md). The team selects
addresses, images, and access paths under delegated authority; the example
manifest is not proof of deployed values and must be completed and validated
for the actual deployment.

## Explicitly out of scope for the MVP

- CALDERA or an open-ended autonomous attacker
- GHOSTS background-traffic simulation
- LocalStack or public-cloud accounts
- Learner-operated red teaming
- Real encryption, disk modification, or Internet-connected targeting

## Source of truth

- Event format: [event-contract-v1.md](contracts/event-contract-v1.md)
- Action safety: [safe-action-contract-v1.md](contracts/safe-action-contract-v1.md)
- Exercise behavior: [exercise-design/02-storyline-and-msel.md](../exercise-design/02-storyline-and-msel.md)
- Telemetry: [exercise-design/03-telemetry-evidence-matrix.md](../exercise-design/03-telemetry-evidence-matrix.md)
- Tools/offline plan: [exercise-design/07-offline-tool-bundle-inventory.md](../exercise-design/07-offline-tool-bundle-inventory.md)
