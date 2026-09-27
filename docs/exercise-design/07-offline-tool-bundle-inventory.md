# Offline Tool Bundle Inventory

**Status:** Draft inventory reflecting Cyber Range information received
September 27, 2026. Exact software versions, final topology, and offline
installation test results remain outstanding.

This document tracks the software and configuration required to deploy the
project without Internet access. It is not evidence that an artifact has been
approved, acquired, or tested. Record the exact artifact version and SHA-256
after acquisition; do not treat a version range in a requirements file as a
resolved version.

## Decision and approval gates

| Item | Current status | Evidence required to close |
|---|---|---|
| Splunk product, license, and 10 GB data limit | Cyber Range confirmed Splunk Enterprise under an educational license with a 10 GB data limit | Record exact Splunk version and verify how the license counts data; monitor usage and define retention/cleanup within the limit |
| Splunk Universal Forwarder compatibility and ingestion method | Team-owned selection and configuration | Select an ingestion method compatible with the actual Splunk version; verify supported forwarder compatibility or validate the chosen alternative |
| Sysmon binary and configuration | Team-owned Windows/AD and telemetry configuration; evaluation licenses available | Select exact binary/version and config, verify license/provenance and hashes, then test on the chosen Windows image |
| VM topology, provisioning, snapshots, and restoration | Team owns provisioning, snapshots, and restoration; can use CITEF or design topology in platform | Select topology and image versions; document repeatable Ansible provisioning and snapshot/restore procedures |
| Scenario VM architecture and images | amd64 VMs supported; Windows 11, Windows Server, and multiple Linux distribution images available; compute not expected to constrain this MVP | Select exact OS images and record versions, architecture, sizing, and destination roles |
| DNS and NTP | Team can configure these through Ansible | Select internal DNS domain and time source; implement and validate configuration |
| Offline artifact delivery | Scenario VMs have no Internet; team can push files to them; no restrictions reported on approach | Stage dependencies/installers/configuration and document the chosen secure transfer, checksum verification, and installation workflow |
| Project runtime package lock and wheelhouse | Not produced | Resolve all runtime dependencies to exact versions, acquire wheels and metadata, record hashes/licenses, and install from the wheelhouse with network disabled |
| Ansible collections and other system installers | Not inventoried in repository | Select deployment host and required collections/system packages, then record exact artifacts, hashes, licenses, and offline installation commands |
| Portal network independence | Not verified | Audit the delivered portal source/build for CDN, remote API, cloud, and online package dependencies; test the built portal with Internet access disabled |
| Clean offline installation | Not tested | Complete and record the procedure in [Offline installation test record](#offline-installation-test-record) on clean amd64 test VMs matching selected target images, with Internet access disabled |
| Artifact licensing and transfer | Team owns software selection and transfer approach; licensed/evaluation artifacts must remain license-compliant | Record license/owner and transfer eligibility for each artifact; keep proprietary installers, secrets, and credentials out of Git |

The Cyber Range confirmed the educational Splunk Enterprise license and its
10 GB data limit, but the exact Splunk version and license accounting details
are not yet recorded. Budget telemetry volume conservatively until the team
verifies how the license measures data. The Cyber Range places no restrictions
on the team's approach to Windows/AD configuration, automation, secrets, or
software transfer; the team remains responsible for compatibility, licensing,
checksums, and offline verification.

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
| Ansible collections | Not declared | Ansible Galaxy or selected source; exact collection owners pending selection | Verify per collection | Pending | Team-managed Ansible control host; exact VM pending | Pin in `requirements.yml`, acquire collection archives, push to control host, install from local paths |
| Ansible and system packages | Not declared | Selected OS distribution and package sources | Verify per artifact | Pending | Team-managed control host and target VMs | Stage approved packages/repository metadata and push to VMs; install without external repositories |
| Splunk Enterprise | Educational-license version not recorded | Cyber Range has an educational license | 10 GB data limit confirmed; detailed terms/version to record | Pending | Splunk VM; placement and provisioning owner pending | Confirm whether it is pre-provisioned or the team must stage an installer; respect license and data limit |
| Splunk Universal Forwarder | Exact version pending compatibility check | Splunk distribution, selected by project team | Verify applicable license/terms | Pending | Approved Windows/Linux telemetry source VMs | If selected, stage compatible local installer and configuration; push to VM and validate without Internet |
| Sysmon binary | Exact version pending team selection | Microsoft Sysinternals | Verify applicable license/terms and evaluation use | Pending | Approved Windows endpoint VMs | Stage selected installer, push to VM, and install locally under the applicable terms |
| Sysmon configuration | Not selected | Project configuration; team-owned | Project-authored; confirm provenance of any included rules | Pending after selection | Approved Windows endpoint VMs | Versioned config file pushed and installed locally alongside Sysmon |
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
  services or documented Cyber Range endpoints; document and justify any
  external dependency.
- Build from the staged local package cache, then serve and exercise the
  production build on a clean VM while Internet egress is denied. Verify
  browser developer tools and host/network logs show no attempted external
  dependency fetch.
- Record the portal build revision, package lock, local asset list, test date,
  VM image, and results below before marking this gate verified.

## Bundle and handling rules

- Keep proprietary installers, licensed binaries, credentials, and secrets out
  of Git. Verify that use and transfer comply with each artifact's license.
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
| Splunk version / Universal Forwarder version / Sysmon version (if applicable) | Pending team selection and compatibility verification |
| Installation commands and local artifact source | Pending |
| Package/config checksum verification | Pending |
| Portal external-request audit | Pending |
| Result, failures, and remediation | Pending |
| Evidence/log location | Pending |

### Test procedure

1. Provision a clean amd64 test VM matching the selected target OS and role. Disable
   Internet egress at the network boundary and verify that an external
   connection cannot be established.
2. Push the versioned bundle using the documented transfer mechanism.
   Verify the bundle and each artifact checksum before installation.
3. Install runtime packages from the local wheelhouse and Ansible collections
   from local archives; install selected system packages and licensed binaries
   only from their staged local sources.
4. Deploy project configuration and the portal, then run the project health
   checks and exercise a representative telemetry path to the approved Splunk
   destination.
5. Inspect installer output, service logs, host/network logs, and browser
   network activity for missing artifacts or attempted Internet access.
   Record every failure; do not silently retry from an online source.
6. Complete the test record and repeat from a clean VM after bundle changes.

Do not mark the bundle as offline-ready until all required target roles pass,
the selected Splunk and Sysmon versions are compatible with the environment
and license terms, the Splunk 10 GB data limit has an operational budget, and
all failures have been resolved or explicitly accepted by the project team.
