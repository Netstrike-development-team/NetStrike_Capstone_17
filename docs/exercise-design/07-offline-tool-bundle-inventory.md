# Offline Tool Bundle Inventory

**Status:** Draft inventory reflecting Cyber Range and team decisions recorded
September 24–27, 2026. Proposed stack is identified; exact artifact versions,
checksums, bundle build, and offline installation test results remain
outstanding for the target deployment environment. The dependency installation
workflow has successfully run on a personal machine while disconnected from
the Internet; target-VM validation remains pending.

This document tracks the proposed software and configuration for an offline
deployment. It is not evidence that an artifact has been acquired, licensed,
approved where required, or tested. Record the exact artifact version and
SHA-256 after acquisition; do not treat a version range in a requirements file
as a resolved version.

## Decision and approval gates

| Item | Current status | Evidence required to close |
|---|---|---|
| Splunk Enterprise and 10 GB data limit | Cyber Range-provided educational license; exact Splunk version and meaning of the 10 GB limit remain unconfirmed | Record product/version and confirm what the 10 GB limit measures; configure and monitor ingestion/retention accordingly |
| Windows telemetry and forwarding | Sysmon, Windows Security logs, PowerShell logs, and Splunk Universal Forwarder | Select compatible versions; confirm applicable license/approval, checksums, collection configuration, and ingestion health |
| Controller, portal, and state | Python 3.11, FastAPI, SQLite; Uvicorn and Pydantic are proposed runtime dependencies | Pin runtime/dependency versions, verify licenses, and bundle all wheels; SQLite is accessed through Python's `sqlite3` module |
| Ansible and remote configuration | `ansible-core` with `ansible.windows`; SSH/WinRM and PowerShell | Pin Ansible and collection versions; stage all wheels and collection archives; test against selected Linux and Windows images |
| Snapshot restoration and readiness | Restore clean VM snapshots; use Ansible mainly for configuration and readiness checks | No 20-minute Ansible reset target; document and test snapshot restore and readiness validation |
| Commercial EDR | Not included in the MVP | Sysmon and Windows logs provide endpoint evidence; restricted NetStrike exercise controls simulate limited containment actions and must be described as exercise controls, not production EDR |
| Mock cloud and impact | Project-owned stateful Python mock; safe marker files and reversible file moves | Keep the mock local; limit changes to allowlisted disposable fixtures; do not add real cloud APIs or encryption |
| Scenario VM architecture and images | amd64 VMs supported; Windows 11, Windows Server, and multiple Linux distribution images available; compute not expected to constrain this MVP | Select exact OS images and record versions, architecture, sizing, and destination roles |
| DNS and NTP | Team can configure these through Ansible | Select internal DNS domain and time source; implement and validate configuration |
| Offline artifact delivery | Scenario VMs have no Internet; team can push files to them; no restrictions reported on approach | Stage dependencies/installers/configuration and document the chosen secure transfer, checksum verification, and installation workflow |
| Student-funded software | No paid software or public-cloud services are required from the student team | Use the Cyber Range-provided Splunk educational license and free/open-source or project-owned components; verify applicable evaluation terms |
| Project runtime package lock and wheelhouse | Not produced | Resolve all runtime dependencies to exact versions, acquire wheels and metadata, record hashes/licenses, and install from the wheelhouse with network disabled |
| Ansible collections and other system installers | `citef-config/requirements.yml` pins `ansible.windows` and `microsoft.ad`; `citef-config/requirements-controller.txt` constrains `ansible-core`; build-time archives and resolved wheel versions are recorded in the generated bundle inventory | Review generated versions, hashes, and licenses, then validate installation on the target VM; system installers remain unselected |
| Portal network independence | Dashboard implementation and static assets are in the repository; external dependency audit and disconnected target test are not recorded | Audit the delivered portal for CDN, external API, cloud, and online package dependencies; test the built portal with Internet access disabled |
| Clean offline installation | Not tested | Complete and record the procedure in [Offline installation test record](#offline-installation-test-record) on clean amd64 test VMs matching selected target images, with Internet access disabled |
| Versioned release bundle | Not built | Include source/release archive, locked Python wheels, pinned Ansible collections, required signed installers/configuration, Splunk inputs and field mappings, playbooks, synthetic fixtures, known-good manifests, and installation/readiness/removal instructions |
| Artifact licensing and transfer | Team owns software selection and transfer approach; use of licensed/evaluation artifacts must remain license-compliant | Record license/owner, approval where required, and transfer eligibility for each artifact; keep proprietary installers, secrets, and credentials out of Git |

The proposed inventory below follows the team's tool choices and PR #105.
Splunk Enterprise is supplied by the Cyber Range under an educational license;
the exact version and what the stated 10 GB limit measures still need
confirmation. The team selects/configures Windows/AD telemetry, automation,
secrets handling, and file transfer, while validating compatibility,
applicable licenses, checksums, and offline operation.

## Repository software inputs

The following are declarations found in the current repository, not a complete
resolved artifact list. Runtime declarations are unpinned or range-based, so
they are insufficient by themselves for a reproducible offline install.
Package licenses, exact resolved versions, and artifact checksums must be
verified against the acquired distribution and its metadata.

| Name | Declared/proposed version | Source / owner | License | SHA-256 | Destination VM | Offline installation method |
|---|---|---|---|---|---|---|
| Python runtime | 3.11 proposed | Python Software Foundation / python.org or selected OS distribution | Python Software Foundation License; verify exact distribution | Pending | `CTRL01` controller/portal/mock service; Ansible control host if colocated | Stage a compatible amd64 OS package/runtime before deployment; include version and package checksum in bundle manifest |
| FastAPI | Exact version not pinned | PyPI / FastAPI project | MIT (verify distribution metadata) | Pending | `CTRL01` | Pin in locked requirements; install from staged wheelhouse using pip `--no-index` |
| Uvicorn | Exact version not pinned | PyPI / Uvicorn project | Verify from distribution metadata | Pending | `CTRL01` | Pin with all transitive dependencies in wheelhouse; install offline |
| Pydantic | Exact version not pinned | PyPI / Pydantic project | Verify from distribution metadata | Pending | `CTRL01` | Pin with all transitive dependencies in wheelhouse; install offline |
| SQLite / Python `sqlite3` | SQLite version bundled with selected Python/runtime; exact version pending | SQLite project / Python runtime | Public domain for SQLite; verify runtime distribution | Pending | `CTRL01` | Use the Python standard-library `sqlite3` module; no separate network service or Python package |
| Jinja templates (if used) | Optional; exact version not pinned | PyPI / Pallets project | Verify from distribution metadata | Pending | `CTRL01` portal | If selected, pin and include wheel/dependencies in local wheelhouse |
| Flask | `>=3.1,<4` (`modules/04-mfa-fatigue-sim/requirements.txt`) | PyPI / Flask project | Verify from distribution metadata | Pending | Project runtime VM; proposed `CTRL01`, confirm topology | Acquire compatible wheel and dependencies; install with pip `--no-index --find-links` |
| requests | `>=2.32,<3` (`modules/04-mfa-fatigue-sim/requirements.txt`) | PyPI / Requests project | Verify from distribution metadata | Pending | Project runtime VM; proposed `CTRL01`, confirm topology | Wheelhouse; pip with `--no-index --find-links` |
| jsonschema (with `format` extra) | `>=4.23,<5` (`shared/requirements.txt`, `modules/04-mfa-fatigue-sim/requirements.txt`, `modules/05-lateral-movement/requirements.txt`, `modules/07-ransomware-sim/requirements.txt`) | PyPI / jsonschema project | Verify for package and transitive dependencies | Pending | Project runtime VM(s); proposed `CTRL01`, confirm topology | Resolve extra and transitive dependencies into wheelhouse; pip offline |
| ldap3 | `>=2.9,<3` (`modules/05-lateral-movement/requirements.txt`) | PyPI / ldap3 project | Verify from distribution metadata | Pending | AD integration runtime VM; proposed `CTRL01`, confirm topology | Wheelhouse; pip with `--no-index --find-links` |
| PyYAML | Unpinned (`modules/06-cloud-exfil/requirements.txt`) | PyPI / PyYAML project | Verify from distribution metadata | Pending | Cloud simulation runtime VM; proposed `CTRL01`, confirm topology | Select and lock a compatible version; wheelhouse; pip offline |
| pycryptodome | Unpinned (`modules/06-cloud-exfil/requirements.txt`) | PyPI / PyCryptodome project | Verify from distribution metadata | Pending | Cloud simulation runtime VM; proposed `CTRL01`, confirm topology | Select and lock a compatible wheel for target OS/Python; wheelhouse; pip offline |
| pytest | `>=7.4` (`requirements-dev.txt`) | PyPI / pytest project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |
| coverage | `>=7.3` (`requirements-dev.txt`) | PyPI / Coverage.py project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |
| pylint | `>=3.0` (`requirements-dev.txt`) | PyPI / Pylint project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |
| bandit | `>=1.7` (`requirements-dev.txt`) | PyPI / Bandit project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |

The FastAPI stack above is the proposed MVP controller/API direction; Flask
and other dependencies below are declarations already in module requirement
files, not confirmation that every module or package is in the final deployed
MVP. Reconcile module scope before producing the release lock. Package roots
do not enumerate transitive dependencies. Generate a fully resolved,
target-platform-specific manifest before acquiring artifacts.
`requirements-dev.txt` dependencies are development/test tools and should not
be included on exercise VMs unless operationally required.

## System tools, collections, installers, and project configuration

The Ansible collection requirements and configuration source are present, and
the workflow now records downloaded collection metadata and resolved Python
artifacts in each generated bundle. A release bundle has not yet been produced
or tested on a target VM. No Splunk/Universal Forwarder installer or Sysmon
binary is present in the current repository inventory. The infrastructure
description is not a tested deployment manifest. Do not infer that Wazuh,
Elastic, or another SIEM in legacy documentation is part of the approved
Splunk-based MVP.

| Name | Version | Source / owner | License | SHA-256 | Destination VM | Offline installation method |
|---|---|---|---|---|---|---|
| `ansible-core` | Exact version not pinned | PyPI / Ansible project | Verify package and dependency licenses | Pending | Team-managed Linux Ansible control host, likely `CTRL01` | Pin and include Python wheels and transitive dependencies; install from local wheelhouse |
| `ansible.windows` collection | Exact version not pinned | Ansible Galaxy / Ansible community | Verify collection license and dependencies | Pending | Ansible control host; configures Windows targets | Pin in `requirements.yml`; download collection archive in advance, push and install from local path |
| SSH client and WinRM dependencies | Exact OS/Python package versions not selected | Selected Linux OS repositories / Python package sources | Verify per package | Pending | Ansible control host; Windows targets use WinRM | Stage OS packages and Python dependencies; configure SSH/WinRM without Internet |
| PowerShell | Version supplied by selected Windows image; exact version pending | Microsoft / Windows image | Windows image license terms | Pending image/build manifest | Windows Server and Windows 11 endpoints | Use image-provided PowerShell for configuration, telemetry setup, and readiness tasks |
| Windows Security event logging | OS-provided; audit policy not configured | Microsoft / Windows image | Windows image license terms | N/A; record configuration revision/hash | Windows endpoints | Configure and validate audit policy offline with Ansible/PowerShell |
| PowerShell logging | OS-provided; policy not configured | Microsoft / Windows image | Windows image license terms | N/A; record configuration revision/hash | Windows endpoints | Configure required logging policy offline with Ansible/PowerShell |
| Splunk Enterprise | Exact version pending | Cyber Range-provided educational license | Educational license; 10 GB limit stated, definition and applicable terms pending | Pending | Splunk instance/VM; provisioning and access details pending | Configure provided deployment, or stage the licensed installer if the team must provision it; no student-purchased license |
| Splunk Universal Forwarder | Exact version must match/compatibly support Splunk deployment | Splunk distribution; selected/configured by team | Verify license and Cyber Range deployment terms | Pending | Windows endpoints; other sources only if required | Pre-stage matching Windows MSI, install/configure silently offline; verify forwarder health and ingestion |
| Sysmon binary | Exact version pending; signed binary required | Microsoft Sysinternals | Applicable Microsoft/Sysinternals terms; confirm permitted evaluation/use | Pending | Windows endpoints | Stage signed binary and checksum; install locally through Ansible/PowerShell |
| Sysmon XML configuration | Exact configuration revision pending | Project-authored, based on selected Sysmon setup | Project-owned; review included rule provenance | Pending | Windows endpoints | Version, hash, and push with bundle; apply locally and validate expected events |
| Splunk HEC inputs and project event mapping | Exact configuration/revision pending | Project-owned Splunk inputs, field mappings, searches, dashboards | Project repository license/content provenance to be confirmed | Pending | Splunk instance | Push/configure locally; project events can use HEC or a monitored file as supported |
| Versioned release archive and manifest | Not built | Project team | Repository license and third-party content provenance to be verified | Generate per release | Transferred to deployment host and target VMs | Include locked wheels, collection archives, approved installers/configuration, playbooks, fixtures, known-good manifests, and install/readiness/removal documentation |
| Event/action schemas and exercise configuration | Repository revision; no release artifact yet | Project repository / project team | Repository license and included-content provenance to be confirmed | Generate at release | `CTRL01` and relevant target VMs | Copy with versioned application bundle; no package-manager/network fetch required |

The project-owned configuration candidates currently in the repository include
`schemas/`, `modules/07-ransomware-sim/config.yaml`, and module source/config
files. Their final destination and required subset depend on the approved
topology. Record checksums for the exact release bundle rather than treating
these source files as transferred installers.

## Portal and external network dependency audit

The current repository contains a `dashboard/` placeholder, not a delivered
FastAPI/SQLite portal implementation or final dependency lock. Therefore,
absence of a CDN, external API, cloud service, or online package dependency
has **not** been verified. The proposed portal is server-rendered HTML/CSS/
JavaScript with local assets and optional Jinja templates; no CDN or external
fonts/scripts are planned. Before accepting the portal:

- Identify and pin all frontend/backend dependencies and bundle required
  static assets locally; do not load scripts, fonts, styles, or other resources
  from a CDN at runtime.
- Inventory every outbound request and integration. The cloud component must
  use the project-owned stateful Python mock, not a public-cloud service; no
  external service is required during exercise delivery.
- Build from the staged local package cache, then serve and exercise the
  production build on a clean VM while Internet egress is denied. Verify
  browser developer tools and host/network logs show no attempted external
  dependency fetch.
- Record the portal build revision, package lock, local asset list, test date,
  VM image, and results below before marking this gate verified.

The MVP does not include a commercial EDR. Sysmon, Windows Security events,
and PowerShell logs provide endpoint evidence. NetStrike's restricted,
allowlisted exercise controls simulate only the containment actions needed
for the scenario; participant and staff documentation must call them exercise
controls, not production EDR.

## Bundle and handling rules

- Keep proprietary installers, licensed binaries, credentials, and secrets out
  of Git. Verify that use and transfer comply with each artifact's license and
  record any required Cyber Range approval before transfer.
- Keep the versioned inventory, lock files, checksums, and installation
  instructions in the project. Push staged files to scenario VMs using the
  team's documented transfer mechanism and a manifest matching this inventory.
- Record SHA-256 for every acquired wheel, collection archive, installer,
  configuration, and release bundle. Verify hashes after transfer and before
  installation.
- Install Python packages only from the staged wheelhouse, for example:
  `python -m pip install --no-index --find-links <wheelhouse> -r <locked-requirements.txt>`.
- Do not use `--trusted-host`, disable certificate checks, or fall back to an
  online package source to make the offline installation pass.

## Offline installation test record

**Status:** The workflow and dependency installation succeeded on a personal
machine with Internet access disconnected. The clean target-VM test has not
been run, so no target-VM or deployment-readiness result is claimed.

Complete this record for each target OS/VM role. Preserve logs that contain no
secrets and link them from the approved project evidence location.

| Field | Result |
|---|---|
| Test date / operator | Personal-machine run; date and operator details not recorded |
| Clean VM image, OS/version, and role | Not applicable to the personal-machine run; clean target VM pending |
| Internet disabled and verified by | Personal machine was disconnected from the Internet during the run; verification method not recorded |
| Bundle release/version and SHA-256 | Pending |
| Python version/architecture and locked requirements checksum | Pending; versions and checksum used in the personal-machine run not recorded |
| `ansible-core` version and `ansible.windows` collection manifest checksum | Pending |
| Splunk version / Universal Forwarder version / Sysmon version (if applicable) | Pending team selection and compatibility verification |
| Windows Security and PowerShell audit policy revision | Pending |
| Installation commands and local artifact source | Dependency installation completed successfully while offline on a personal machine; exact commands and artifact source not recorded |
| Package/config checksum verification | Pending |
| Portal external-request audit | Pending |
| Snapshot restore and Ansible readiness-check result | Pending |
| Splunk event sources, ingestion validation, and 10 GB usage measurement | Pending |
| Result, failures, and remediation | Personal-machine workflow and dependency installation succeeded offline; target-VM result pending |
| Evidence/log location | Pending |

### Test procedure

1. Provision a clean amd64 test VM matching the selected target OS and role. Disable
   Internet egress at the network boundary and verify that an external
   connection cannot be established.
2. Push the versioned bundle using the documented transfer mechanism.
   Verify the bundle and each artifact checksum before installation.
3. Install locked Python 3.11 dependencies from the local wheelhouse and
   `ansible.windows` from its pinned local archive; install selected system
   packages and licensed binaries only from their staged local sources.
4. Use Ansible over SSH/WinRM to configure DNS/NTP, Windows Security and
   PowerShell logging, Sysmon, Universal Forwarder, controller, portal, and
   mock service. Run configuration/readiness checks.
5. Restore the clean VM snapshots and verify that readiness checks pass.
   Exercise a representative Windows and project-event telemetry path to
   Splunk (using Universal Forwarder for Windows events and HEC or monitored
   file for project events, as configured).
6. Inspect installer output, service logs, host/network logs, and browser
   network activity for missing artifacts or attempted Internet access.
   Record every failure; do not silently retry from an online source.
7. Complete the test record and repeat from clean snapshots after bundle changes.

Do not mark the bundle as offline-ready until all required target roles pass,
the selected Splunk and Sysmon versions are compatible with the environment
and license terms, the exact Splunk 10 GB accounting is understood and
operationally budgeted, snapshots restore to a validated baseline, and all
failures have been resolved or explicitly accepted by the project team.
