# Offline Tool Bundle Inventory

**Status:** Draft inventory; no Cyber Range approvals or offline installation
test have been recorded.

This document tracks the software and configuration required to deploy the
project without Internet access. It is not evidence that an artifact has been
approved, acquired, or tested. Record the exact artifact version and SHA-256
after acquisition; do not treat a version range in a requirements file as a
resolved version.

## Decision and approval gates

| Item | Current status | Evidence required to close |
|---|---|---|
| Cyber Range Splunk product, edition, exact version, and meaning of the stated 10 GB limit | Pending CITEF | Written CITEF confirmation of version and whether 10 GB is license, storage, ingestion, or another limit |
| Splunk Universal Forwarder compatibility and approved ingestion method | Pending CITEF | Supported forwarder version for the confirmed Splunk version, plus approval for HEC, forwarder, syslog, or monitored-file ingestion |
| Sysmon binary and configuration | Pending CITEF | CITEF approval of the exact binary/version and configuration; checksum and license/owner recorded before transfer |
| Project runtime package lock and wheelhouse | Not produced | Resolve all runtime dependencies to exact versions, acquire wheels and metadata, record hashes/licenses, and install from the wheelhouse with network disabled |
| Ansible collections and other system installers | Not inventoried in repository | Confirm deployment host and required collections/system packages, then record exact artifacts, hashes, licenses, and offline installation commands |
| Portal network independence | Not verified | Audit the delivered portal source/build for CDN, remote API, cloud, and online package dependencies; test the built portal with Internet access disabled |
| Clean offline installation | Not tested | Complete and record the procedure in [Offline installation test record](#offline-installation-test-record) on a clean test VM with Internet access disabled |
| Artifact transfer and licensed software | Pending CITEF | Confirm approved transfer mechanism and obtain written approval before transferring any licensed installer |

The stated 10 GB limit is not interpreted here because its measurement and the
Splunk deployment details have not been confirmed. The project must not select
a Splunk or Universal Forwarder version, or transfer Sysmon or another licensed
binary, until CITEF has approved the exact choice.

## Repository software inputs

The following are declarations found in the current repository, not a complete
resolved artifact list. Runtime declarations are unpinned or range-based, so
they are insufficient by themselves for a reproducible offline install.
Package licenses, exact resolved versions, and artifact checksums must be
verified against the acquired distribution and its metadata.

| Name | Declared version | Source / owner | License | SHA-256 | Destination VM | Offline installation method |
|---|---|---|---|---|---|---|
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

The table records package roots; it does not yet enumerate their transitive
dependencies. Generate a fully resolved, target-platform-specific manifest
before acquiring artifacts. The `requirements-dev.txt` dependencies are
development/test tools and should not be included on exercise VMs unless an
approved operational need is documented.

## Collections, installers, and project configuration

No active Ansible collection requirements file, package lock/wheelhouse,
Splunk/Universal Forwarder installer, or Sysmon binary is present in the
current repository inventory. The `citef-config/` directory currently contains
only a placeholder, and the infrastructure description is not a tested
deployment manifest. Do not infer that Wazuh, Elastic, or another SIEM in
legacy documentation is part of the approved Splunk-based MVP.

| Name | Version | Source / owner | License | SHA-256 | Destination VM | Offline installation method |
|---|---|---|---|---|---|---|
| Ansible collections | Not declared | Ansible Galaxy or approved internal mirror; exact collection owners pending selection | Verify per collection | Pending | Approved Ansible control host; pending CITEF | Pin in `requirements.yml`, acquire collection archives, install from local paths |
| Ansible and system packages | Not declared | Approved OS repositories or internally transferred packages; pending CITEF | Verify per artifact | Pending | Approved Ansible control host and target VMs | Stage approved OS packages/repository metadata; install without external repositories |
| Splunk Enterprise/other CITEF Splunk product | Exact product/version pending CITEF | Cyber Range-provided; owner/admin pending | CITEF to confirm license and transfer approval | Pending; record only if approved for transfer | CITEF-managed Splunk VM | CITEF-approved installation/upgrade procedure; do not include in Git |
| Splunk Universal Forwarder | Exact version pending compatibility approval | Splunk/CITEF; transfer owner pending | CITEF to confirm license and transfer approval | Pending; record only if approved for transfer | Approved Windows/Linux telemetry source VMs | CITEF-approved local installer and silent-install configuration |
| Sysmon binary | Exact version pending CITEF approval | Microsoft Sysinternals; acquisition/transfer owner pending | Verify applicable license and CITEF transfer approval | Pending; do not transfer before approval | Approved Windows endpoint VMs | CITEF-approved local installer, with the approved configuration |
| Sysmon configuration | Not selected/approved | Project configuration; approval owner CITEF | Project-authored; confirm provenance of any included rules | Pending after approval | Approved Windows endpoint VMs | Versioned config file installed locally alongside approved Sysmon |
| Event/action schemas and exercise configuration | Repository revision; no release artifact yet | Project repository / project team | Repository license and included-content provenance to be confirmed | Generate at release | Project runtime VM(s); proposed `CTRL01`, confirm topology | Copy with versioned application bundle; no package-manager/network fetch required |

The project-owned configuration candidates currently in the repository include
`schemas/`, `modules/07-ransomware-sim/config.yaml`, and module source/config
files. Their final destination and required subset depend on the approved
topology. Record checksums for the exact release bundle rather than treating
these source files as transferred installers.

## Portal and external network dependency audit

The current repository contains a `dashboard/` placeholder, not a delivered
portal implementation or frontend dependency manifest. Therefore, absence of a
CDN, external API, cloud service, or online package dependency has **not** been
verified. Before accepting the portal:

- Identify and pin all frontend/backend dependencies and bundle required
  static assets locally; do not load scripts, fonts, styles, or other resources
  from a CDN at runtime.
- Inventory every outbound request and integration. Use project-owned local
  services or CITEF-approved endpoints only; document any exception and obtain
  approval.
- Build from the staged local package cache, then serve and exercise the
  production build on a clean VM while Internet egress is denied. Verify
  browser developer tools and host/network logs show no attempted external
  dependency fetch.
- Record the portal build revision, package lock, local asset list, test date,
  VM image, and results below before marking this gate verified.

## Bundle and handling rules

- Keep proprietary installers, licensed binaries, credentials, and secrets out
  of Git. Transfer licensed artifacts only after CITEF approves the exact
  artifact and transfer method.
- Keep the versioned inventory, lock files, checksums, and installation
  instructions in the project. Distribute approved binaries through the
  CITEF-approved artifact-transfer mechanism, with a manifest that matches
  this inventory.
- Record SHA-256 for every acquired wheel, collection archive, installer,
  configuration, and release bundle. Verify hashes after transfer and before
  installation.
- Install Python packages only from the staged wheelhouse, for example:
  `python -m pip install --no-index --find-links <wheelhouse> -r <locked-requirements.txt>`.
- Do not use `--trusted-host`, disable certificate checks, or fall back to an
  online package source to make the offline installation pass.

## Offline installation test record

**Status:** Not run. No clean-VM result is claimed.

Complete this record for each target OS/VM role. Preserve logs that contain no
secrets and link them from the approved project evidence location.

| Field | Result |
|---|---|
| Test date / operator | Pending |
| Clean VM image, OS/version, and role | Pending |
| Internet disabled and verified by | Pending |
| Bundle release/version and SHA-256 | Pending |
| Python version/architecture and locked requirements checksum | Pending |
| Ansible version and collection manifest checksum | Pending |
| Splunk version / Universal Forwarder version / Sysmon version (if applicable) | Pending CITEF approval |
| Installation commands and local artifact source | Pending |
| Package/config checksum verification | Pending |
| Portal external-request audit | Pending |
| Result, failures, and remediation | Pending |
| Evidence/log location | Pending |

### Test procedure

1. Provision a clean test VM matching the approved target OS and role. Disable
   Internet egress at the network boundary and verify that an external
   connection cannot be established.
2. Transfer only the approved, versioned bundle using the approved mechanism.
   Verify the bundle and each artifact checksum before installation.
3. Install runtime packages from the local wheelhouse and Ansible collections
   from local archives; install approved system packages and licensed binaries
   only from their staged local sources.
4. Deploy project configuration and the portal, then run the project health
   checks and exercise a representative telemetry path to the approved Splunk
   destination.
5. Inspect installer output, service logs, host/network logs, and browser
   network activity for missing artifacts or attempted Internet access.
   Record every failure; do not silently retry from an online source.
6. Complete the test record and repeat from a clean VM after bundle changes.

Do not mark the bundle as offline-ready until all required target roles pass,
the Splunk and Sysmon choices are confirmed by CITEF, and all failures have
been resolved or explicitly accepted by the Cyber Range.
