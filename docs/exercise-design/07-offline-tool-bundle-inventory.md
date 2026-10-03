# Offline tool bundle inventory and deployment decisions

**Status:** The CI workflow builds and verifies a Python runtime/dependency
bundle for the declared requirements, but it does not yet produce a complete
release artifact for all controller dependencies, licensed installers, or final
target-VM deployment. The bundle guide and this inventory together define the
current tool stack, approval gates, and installation boundaries.

This document is the consolidated source for:

- offline bundle scope and artifact inventory;
- tool and approval decisions for the exercise;
- installation and readiness expectations for offline deployment; and
- the current gaps that still need verification before release.

It supersedes the earlier 07 planning notes and should be used alongside
[06-citef-requirements-and-approval.md](06-citef-requirements-and-approval.md)
and the [CITEF configuration guide](../../citef-config/README.md).

## Decision and approval gates

| Item | Current status | Evidence required to close |
|---|---|---|
| Splunk Enterprise and 10 GB data limit | Cyber Range-provided educational license; exact Splunk version and meaning of the 10 GB limit remain unconfirmed | Record product/version and confirm what the 10 GB limit measures; configure and monitor ingestion/retention accordingly |
| Windows telemetry and forwarding | Sysmon, Windows Security logs, PowerShell logs, and Splunk Universal Forwarder | Select compatible versions; confirm applicable license/approval, checksums, collection configuration, and ingestion health |
| Controller, portal, and state | Python 3.11, FastAPI, SQLite; Uvicorn and Pydantic are runtime dependencies under review | Pin runtime/dependency versions, verify licenses, and bundle all wheels; SQLite is accessed through Python's `sqlite3` module |
| Ansible and remote configuration | `ansible-core` with `ansible.windows`; SSH/WinRM and PowerShell | Pin Ansible and collection versions; stage all wheels and collection archives; test against selected Linux and Windows images |
| Snapshot restoration and readiness | Restore clean VM snapshots; use Ansible mainly for configuration and readiness checks | Document and test snapshot restore and readiness validation rather than relying on a 20-minute reset workflow |
| Commercial EDR | Not included in the MVP | Sysmon and Windows logs provide endpoint evidence; restricted NetStrike exercise controls simulate limited containment actions and must be described as exercise controls, not production EDR |
| Mock cloud and impact | Project-owned stateful Python mock; safe marker files and reversible file moves | Keep the mock local; limit changes to allowlisted disposable fixtures; do not add real cloud APIs or encryption |
| Scenario VM architecture and images | amd64 VMs are the expected target; Windows 11, Windows Server, and multiple Linux distribution images are available | Select exact OS images and record versions, architecture, sizing, and destination roles |
| DNS and NTP | Team can configure these through Ansible | Select an internal DNS domain and time source; implement and validate configuration |
| Offline artifact delivery | Scenario VMs have no Internet; the team can push files to them | Stage dependencies, installers, configuration, and transfer workflow; record checksum verification before deployment |
| Student-funded software | No paid software or public-cloud services are required from the student team | Use the Cyber Range-provided Splunk educational license and free/open-source or project-owned components; verify evaluation terms |
| Project runtime package lock and wheelhouse | Not yet complete | Resolve all runtime dependencies to exact versions, acquire wheels and metadata, record hashes/licenses, and install from the wheelhouse with network disabled |
| Ansible collections and other system installers | `citef-config/requirements.yml` pins `ansible.windows` and `microsoft.ad`; `citef-config/requirements-controller.txt` constrains `ansible-core` | Review generated versions, hashes, and licenses, then validate installation on the target VM; system installers remain unselected |
| Portal network independence | Dashboard implementation and static assets are in the repository; external dependency audit and disconnected target test are not recorded | Audit the portal for CDN, external API, cloud, and online package dependencies; test the built portal with Internet access disabled |
| Clean offline installation | Not yet tested on a clean target VM | Complete and record the procedure in the offline installation test record below on clean amd64 test VMs matching selected target images with Internet access disabled |
| Versioned release bundle | Not yet built | Include source/release archive, locked Python wheels, pinned Ansible collections, required signed installers/configuration, Splunk inputs and field mappings, playbooks, synthetic fixtures, known-good manifests, and installation/readiness/removal instructions |
| Artifact licensing and transfer | Team owns software selection and transfer approach; licensed/evaluation artifacts must remain compliant | Record license/owner, approval where required, and transfer eligibility for each artifact; keep proprietary installers, secrets, and credentials out of Git |

Requirements ranges are not resolved versions. Record exact acquired versions and
SHA-256 values here; do not assume that a repository declaration is already
represented in the generated bundle.

## Operational decisions

- Reuse the Cyber Range's Splunk deployment instead of introducing a second SIEM.
- Keep cloud activity in the local mock service to avoid public-cloud accounts and
  internet dependencies during play.
- Use host telemetry with narrowly allowlisted exercise controls instead of adding
  a commercial EDR dependency. These controls are not production EDR.
- Use Ansible for configuration and readiness checks, then restore clean snapshots
  between deliveries.
- Treat the CI-built Python bundle as a runtime bootstrap only; it is not a complete
  offline deployment package until the inventory and test record are complete.

## Repository software inputs

The following are declarations found in the current repository, not a complete
resolved artifact list. Runtime declarations are unpinned or range-based, so they
are insufficient by themselves for a reproducible offline install. Package
licenses, exact resolved versions, and artifact checksums must be verified
against the acquired distribution and its metadata.

| Name | Declared/proposed version | Source / owner | License | SHA-256 | Destination VM | Offline installation method |
|---|---|---|---|---|---|---|
| Python runtime | CPython 3.11.16 in the current offline-bundle workflow | `python-build-standalone` distribution | Python Software Foundation License; verify exact distribution terms | Generated in bundle | `CTRL01` controller/portal/mock service | The workflow stages the portable runtime and records its version/source in the bundle inventory; validate compatibility on the selected target image |
| FastAPI | `>=0.115,<1` (`dashboard/requirements.txt`) | PyPI / FastAPI project | MIT (verify distribution metadata) | Pending | `CTRL01` | Lock and stage with dashboard requirements |
| Uvicorn | `>=0.30,<1` (`dashboard/requirements.txt`) | PyPI / Uvicorn project | Verify from distribution metadata | Pending | `CTRL01` | Lock and stage with dashboard requirements |
| Pydantic | Transitive FastAPI dependency; exact version not pinned | PyPI / Pydantic project | Verify from distribution metadata | Pending | `CTRL01` | Resolve and lock transitively with dashboard requirements |
| httpx | `>=0.27,<1` (`dashboard/requirements.txt`) | PyPI / HTTPX project | Verify from distribution metadata | Pending | `CTRL01` | Lock and stage with dashboard requirements |
| SQLite / Python `sqlite3` | SQLite version bundled with the selected Python runtime; exact version pending | SQLite project / Python runtime | Public domain for SQLite; verify runtime distribution | Pending | `CTRL01` | Use the Python standard-library `sqlite3` module; no separate network service or Python package |
| Jinja templates (if used) | Optional; exact version not pinned | PyPI / Pallets project | Verify from distribution metadata | Pending | `CTRL01` portal | If selected, pin and include the correct wheel and dependencies in the wheelhouse |
| Flask | `>=3.1,<4` (`modules/04-mfa-fatigue-sim/requirements.txt`) | PyPI / Flask project | Verify from distribution metadata | Pending | Project runtime VM; proposed `CTRL01`, confirm topology | Acquire a compatible wheel and install offline from the local wheelhouse |
| requests | `>=2.32,<3` (`modules/04-mfa-fatigue-sim/requirements.txt`) | PyPI / Requests project | Verify from distribution metadata | Pending | Project runtime VM; proposed `CTRL01`, confirm topology | Wheelhouse installation with `pip --no-index --find-links` |
| jsonschema (with `format` extra) | `>=4.23,<5` (`shared/requirements.txt`; also declared in `citef-config/requirements-validator.txt` and `dashboard/requirements.txt`) | PyPI / jsonschema project | Verify package and transitive dependency metadata | Pending | Ansible control host and `CTRL01`; confirm topology | Confirm the generated lock and checksum; other dashboard dependencies are not currently workflow inputs |
| ldap3 | `>=2.9,<3` (`modules/05-lateral-movement/requirements.txt`) | PyPI / ldap3 project | Verify from distribution metadata | Pending | AD integration runtime VM; proposed `CTRL01`, confirm topology | Wheelhouse installation with `pip --no-index --find-links` |
| PyYAML | Unpinned (`modules/06-cloud-exfil/requirements.txt`) | PyPI / PyYAML project | Verify from distribution metadata | Pending | Cloud simulation runtime VM; proposed `CTRL01`, confirm topology | Select and lock a compatible version for the target OS and install offline |
| pycryptodome | Unpinned (`modules/06-cloud-exfil/requirements.txt`) | PyPI / PyCryptodome project | Verify from distribution metadata | Pending | Cloud simulation runtime VM; proposed `CTRL01`, confirm topology | Select and lock a compatible wheel for target OS/Python and install offline |
| pytest | `>=7.4` (`requirements-dev.txt`) | PyPI / pytest project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |
| coverage | `>=7.3` (`requirements-dev.txt`) | PyPI / Coverage.py project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |
| pylint | `>=3.0` (`requirements-dev.txt`) | PyPI / Pylint project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |
| bandit | `>=1.7` (`requirements-dev.txt`) | PyPI / Bandit project | Verify from distribution metadata | Pending | Build/test VM only | Dev/test wheelhouse; not part of delivery runtime unless required |

The FastAPI stack above is the current controller/API implementation. Flask and
other module dependency entries are declarations already present in module
requirement files; they are not confirmation that every package is included in
the final deployed MVP. Reconcile module scope before producing the release lock.
Package roots do not enumerate transitive dependencies, and `requirements-dev.txt`
should not be included on exercise VMs unless operationally required.

## System tools, collections, installers, and project configuration

The Ansible collection requirements and configuration source are present, and the
workflow records downloaded collection metadata and resolved Python artifacts in
each generated bundle. A release bundle has not yet been produced or tested on a
target VM. No Splunk/Universal Forwarder installer or Sysmon binary is present in
this repository inventory. Do not infer that Wazuh, Elastic, or another SIEM in
legacy documentation is part of the approved Splunk-based MVP.

| Name | Version | Source / owner | License | SHA-256 | Destination VM | Offline installation method |
|---|---|---|---|---|---|---|
| `ansible-core` | Exact version not pinned | PyPI / Ansible project | Verify package and dependency licenses | Pending | Team-managed Linux Ansible control host, likely `CTRL01` | Pin and include Python wheels and transitive dependencies; install from a local wheelhouse |
| `ansible.windows` collection | 3.8.0 (`citef-config/requirements.yml`) | Ansible Galaxy / Ansible community | Verify collection license and dependencies | Pending | Ansible control host; configures Windows targets | Download the collection archive in advance, record its hash, transfer it locally, and install from the local path |
| `microsoft.ad` collection | 1.12.1 (`citef-config/requirements.yml`) | Ansible Galaxy / Ansible community | Verify collection license and dependencies | Pending | Ansible control host; configures Active Directory | Download the collection archive in advance, record its hash, transfer it locally, and install from the local path |
| SSH client and WinRM dependencies | Exact OS/Python package versions not selected | Selected Linux OS repositories / Python package sources | Verify per package | Pending | Ansible control host; Windows targets use WinRM | Stage OS packages and Python dependencies; configure SSH/WinRM without Internet |
| PowerShell | Version supplied by the selected Windows image; exact version pending | Microsoft / Windows image | Windows image license terms | Pending image/build manifest | Windows Server and Windows 11 endpoints | Use the image-provided PowerShell for configuration, telemetry setup, and readiness tasks |
| Windows Security event logging | OS-provided; audit policy not configured | Microsoft / Windows image | Windows image license terms | N/A; record configuration revision/hash | Windows endpoints | Configure and validate the audit policy offline with Ansible/PowerShell |
| PowerShell logging | OS-provided; policy not configured | Microsoft / Windows image | Windows image license terms | N/A; record configuration revision/hash | Windows endpoints | Configure required logging policy offline with Ansible/PowerShell |
| Splunk Enterprise | 10.0.1, confirmed 2026-10-02 | Cyber Range-provided educational license | Educational license terms and deployment approval to be recorded | Pending | Splunk instance/VM; underlying OS, provisioning, and access details pending | Configure the provided deployment, or stage its licensed installer if the team must provision it |
| Splunk Universal Forwarder | Exact version must be confirmed as compatible with Splunk Enterprise 10.0.1 | Splunk distribution; selected/configured by the team | Verify license and Cyber Range deployment terms | Pending | Windows endpoints; other sources only if required | Pre-stage a matching Windows MSI; install and configure silently offline; verify forwarder health and ingestion |
| Sysmon binary | Exact version pending; signed binary required | Microsoft Sysinternals | Applicable Microsoft/Sysinternals terms; confirm permitted evaluation/use | Pending | Windows endpoints | Stage the signed binary and checksum; install locally through Ansible/PowerShell |
| Sysmon XML configuration | Exact configuration revision pending | Project-authored, based on the selected Sysmon setup | Project-owned; review included rule provenance | Pending | Windows endpoints | Version, hash, and push with the bundle; apply locally and validate expected events |
| Splunk HEC inputs and project event mapping | Exact configuration/revision pending | Project-owned Splunk inputs, field mappings, searches, dashboards | Project repository license/content provenance to be confirmed | Pending | splunk instance | Push/configure locally; project events can use HEC or a monitored file as supported |
| Complete CITEF release bundle and manifest | Not assembled: CI currently produces only the Python runtime/dependency archive | Project team | Repository license and third-party content provenance to be verified | Generate per release | Transferred to deployment host and target VMs | Create and verify a source archive from the matching reviewed revision; add missing locked controller dependencies, approved installers/configuration, playbooks, fixtures, and manifest |
| Event/action schemas and exercise configuration | Repository revision; no release artifact yet | Project repository / project team | Repository license and included-content provenance to be confirmed | Generate at release | `CTRL01` and relevant target VMs | Copy with the versioned application bundle; no package-manager or network fetch should be required |

The project-owned configuration candidates currently in the repository include
`schemas/`, `modules/07-ransomware-sim/config.yaml`, and other module source/config
files. Their final destination and required subset depend on the approved topology.
Record checksums for the exact release bundle rather than treating source files as
transferred installers.

## Portal and external network dependency audit

The repository contains a FastAPI/SQLite portal. The CI Python bundle does not
package the portal source or all of its requirements. Absence of a CDN, external
API, cloud service, or online package dependency has not been verified on a clean
deployment VM. The portal is a server-rendered HTML/CSS/JavaScript app with local
assets; no CDN or external fonts/scripts are planned. Before accepting the portal:

- Identify and pin all frontend/backend dependencies and bundle required static
  assets locally; do not load scripts, fonts, styles, or other resources from a
  CDN at runtime.
- Inventory every outbound request and integration. The cloud component must use
  the project-owned stateful Python mock, not a public-cloud service; no external
  service is required during exercise delivery.
- Build from the staged local package cache and serve the production build on a
  clean VM while Internet egress is denied. Verify that browser developer tools
  and host/network logs show no attempted external dependency fetch.
- Record the portal build revision, package lock, local asset list, test date, VM
  image, and results before marking this gate verified.

## Handling

Record per-artifact license, approval, version, and SHA-256 in the tables above.
Keep proprietary installers, credentials, and secrets out of Git. Use the
[offline bundle guide](../offline-bundle.md) for Python bundle installation and
the [CITEF guide](../../citef-config/README.md) for collection staging and
config deployment workflow.

## Offline installation test record

**Status:** The workflow and dependency installation succeeded on a personal
machine with Internet access disconnected. The clean target-VM test has not been
run, so no target-VM or deployment-readiness result is claimed.

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
| Splunk version / Universal Forwarder version / Sysmon version (if applicable) | Splunk Enterprise 10.0.1 confirmed; Universal Forwarder and Sysmon versions pending compatibility verification |
| Windows Security and PowerShell audit policy revision | Pending |
| Installation commands and local artifact source | Dependency installation completed successfully while offline on a personal machine; exact commands and artifact source not recorded |
| Package/config checksum verification | Pending |
| Portal external-request audit | Pending |
| Snapshot restore and Ansible readiness-check result | Pending |
| Splunk event sources, ingestion validation, and 10 GB usage measurement | Pending |
| Result, failures, and remediation | Personal-machine workflow and dependency installation succeeded offline; target-VM result pending |
| Evidence/log location | Pending |

### Test procedure

1. Provision a clean amd64 test VM matching the selected target OS and role.
   Disable Internet egress at the network boundary and verify that an external
   connection cannot be established.
2. Push the versioned bundle using the documented transfer mechanism and verify
   the bundle and each artifact checksum before installation.
3. Install locked Python 3.11 dependencies from the local wheelhouse and
   `ansible.windows` from its pinned local archive; install selected system
   packages and licensed binaries only from staged local sources.
4. Use Ansible over SSH/WinRM to configure DNS/NTP, Windows Security and
   PowerShell logging, Sysmon, Universal Forwarder, controller, portal, and mock
   service. Run configuration and readiness checks.
5. Restore clean VM snapshots and verify readiness checks. Exercise a
   representative Windows and project-event telemetry flow to Splunk, using the
   configured Universal Forwarder for Windows events and HEC or a monitored file
   for project events.
6. Inspect installer output, service logs, host/network logs, and browser network
   activity for missing artifacts or attempted Internet access. Record every
   failure; do not silently retry from an online source.
7. Complete the test record and repeat from clean snapshots after bundle changes.

Do not mark the bundle as offline-ready until all required target roles pass,
the selected Splunk and Sysmon versions are compatible with the environment and
license terms, planned ingestion is budgeted below the confirmed 10 GB per-day
limit and storage/retention below the 300 GB disk capacity, snapshots restore to
a validated baseline, and all failures have been resolved or explicitly accepted
by the project team.
