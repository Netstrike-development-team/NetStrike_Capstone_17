# CITEF topology and readiness workflow

**Owner:** Patrick Luu  
**Status:** Proposed design; not approved for CITEF deployment  
**Tracking:** [#103](https://github.com/Netstrike-development-team/NetStrike_Capstone_17/issues/103), [#79](https://github.com/Netstrike-development-team/NetStrike_Capstone_17/issues/79)

This package defines a proposed logical topology and post-restore readiness
gate; it does not specify live CITEF assignments or credentials. The range has
confirmed amd64 VM availability, team-managed DNS/NTP through Ansible, offline
scenario VMs, offline file transfer, Splunk Enterprise, and clean snapshots.
The planning images are Ubuntu Server 26.04 LTS, Windows Server 2025 LTSC, and
Windows 11 26H2. Images, builds, and RFC1918 addresses below are assumptions,
not approvals. Confirm availability and network overlap with CITEF. The local
manifest validates configuration only, not egress or CITEF approval; record
both separately before deployment.

## Proposed logical topology

![Proposed NetStrike CITEF example environment network diagram](../docs/network-diagram.png)

The diagram and values below are planning examples, not firewall rules,
routes, browser source addresses, control-host placement, or management
interfaces. Confirm these with CITEF.

Keep `DC01`, `FIN-WS01`, and `SPLUNK01` on separate VMs. The initial
zero-cost layout places project-owned Linux services on `CTRL01`; `FILE01` is
a controller-managed logical fixture store on `CTRL01`, outside participant
and attack-module administration. If the range has capacity and approves it,
`FILE01` can instead be a separate Linux VM. Never consolidate the controller,
domain controller, participant endpoint, or Splunk.

| Asset | Proposed placement / IP / DNS | Purpose |
|---|---|---|
| `CTRL01` | Ubuntu Server 26.04 amd64; `10.77.0.11`, `ctrl01.simcorp.test` | Staff controller, portal, event ledger, action adapters, mock services |
| `DC01` | Windows Server 2025 LTSC; `10.77.0.10`, `dc01.simcorp.test` | Synthetic AD; internal DNS/NTP source |
| `FIN-WS01` | Windows 11 26H2; `10.77.0.20`, `fin-ws01.simcorp.test` | Participant endpoint and telemetry |
| `SPLUNK01` | Range-supported Splunk Enterprise 10.0.1; `10.77.0.30`, `splunk01.simcorp.test` | SIEM; confirmed 10 GB/day ingestion and 300 GB disk limits |
| `FILE01` | Logical service on `CTRL01` or optional Linux VM | Disposable fixtures and controller-managed known-good copy |

### Planning image and address assumptions

As of October 2, 2026, the candidate releases are:

| VM | Planning image | Current vendor release evidence |
|---|---|---|
| `CTRL01` | Ubuntu Server 26.04 LTS amd64 | [Ubuntu release list](https://wiki.ubuntu.com/Releases) identifies 26.04 (Resolute Raccoon) as the latest release |
| `DC01` | Windows Server 2025 LTSC amd64 | [Microsoft Windows Server release information](https://learn.microsoft.com/en-us/windows/release-health/windows-server-release-info) identifies Windows Server 2025 as current LTSC |
| `FIN-WS01` | Windows 11 26H2 amd64 | [Microsoft Windows 11 release information](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information) lists 26H2 as the latest generally available feature release |

At acquisition, record each image identifier, edition, architecture,
build/update level, and SHA-256. As of September 2026, the cited Windows builds
are 11 26H2 build 26300.9550 and Server 2025 build 26100.33451. Stage updates
and packages before transfer; VMs have no Internet. Verify Ansible and Splunk
support the selected OSes; do not assume the range's Splunk host can run
Ubuntu 26.04.

The proposed exercise subnet is `10.77.0.0/24`; `10.77.1.0/24` is reserved
for management. Configure `simcorp.test` DNS on `DC01` and point scenario VMs
to `10.77.0.10`. Use `DC01` as the isolated time source/PDC emulator; Linux
and non-domain services use its NTP service, while domain members use domain
time. There is no public upstream. To use a
separate NTP server (e.g. while `DC01` does not exist), set
`network.ntp_servers` to its private IPv4 address (it may be outside the
exercise subnet; `DC01` is no longer required in the list) and pass
`-e external_ntp=true` so Linux (chrony) and Windows (w32time, including `DC01` once it exists) sync from those servers and are validated. Before snapshot capture, verify forward
and reverse DNS and clock skew. Confirm non-overlap with CITEF and place
approved addresses in the local manifest before generating inventory.

Limit participant/simulated-action access to `FIN-WS01` and allowlisted
services. Keep Ansible, controller, Splunk administration, hypervisor, and
snapshot controls staff-only. Use CITEF's isolated network and management
path; no bridged/NAT Internet path. CITEF must supply actual subnets and rules.

## Range-owner decisions required before deployment

Confirm and record the following with Zian/Julien, coordinating dates and
delivery with Latifa:

| Decision | Required evidence |
|---|---|
| VM mapping and compute | Exact amd64 image/version, vCPU, RAM, disk, owner, and snapshot-capable asset ID for each physical host |
| Addresses and DNS | Approved non-overlapping exercise/management CIDRs, static host addresses, FQDNs, DNS server addresses, and records resolving each host to its approved address |
| Time | Approved NTP source, service/configuration on each VM, and accepted maximum clock skew |
| Firewall and access | Written default-deny Internet policy; participant, controller, Splunk, SSH, and WinRM paths/ports; management reachability during endpoint isolation |
| Identity | Approved exercise domain, baseline synthetic accounts and group memberships, AD administration path, and reset behavior |
| Telemetry | Splunk product/version and capacity are recorded above; still confirm URL, source/index conventions, required data-source probes, role boundaries, and credential injection method |
| Offline delivery | Reviewed bundle version/hash, approved transfer route, host-side checksum verification, and licensed installer approvals |
| Safety response | Named emergency-stop operator, tested staff contact channel, egress-policy verifier, failed-restore escalation path, and evidence-retention requirement |
| Snapshot ownership | Operator and immutable snapshot/image identifier for every physical host; restore steps and escalation owner |

The environment questionnaire in
[`../docs/exercise-design/06-citef-requirements-and-approval.md`](../docs/exercise-design/06-citef-requirements-and-approval.md)
remains the decision record. A proposed value is not an approved value.

The team owns Ansible configuration of DNS and NTP; this is not a Cyber Range
service dependency. Select an approved internal DNS domain/host and NTP
endpoint, then configure and validate them on every VM. Scenario VMs have no
Internet access, so package installation, time synchronization, name
resolution, and telemetry must not depend on public endpoints. Choose Linux
images whose supported network/time services can be configured by the pinned
Ansible roles, or add and test the matching distribution-specific role before
the image is approved.

## Approved manifest and generated inventory

Copy `environment.example.json` to ignored `environment.json`; populate it
only with approved, non-secret values and never commit it. It contains only
inputs consumed by Ansible and inventory generation. Record image assumptions,
management CIDR, snapshot IDs, and restore ownership in the decision record,
not the manifest. The JSON Schema checks fields, types, allowed values and
formats; `validate_environment.py` checks network overlap/membership, asset
mappings, DNS/domain relationships, artifact paths, and endpoint/port
consistency. Validation and inventory rendering both run these gates. The
controller source comes from Git; runtime and wheelhouse integrity uses
`SHA256SUMS`. Universal Forwarder packages also use vendor SHA-512 checks;
Splunk REST supports internal HTTP or HTTPS.

`identity_baseline.users` defines the exact domain users under
`search_base_dn`, including enabled state and group memberships. Readiness
compares it with AD to catch unexpected, missing, disabled, or mis-grouped
accounts.

For isolated tests only, omit `offline_artifacts.universal_forwarder.receiver_ca`
and controller `tls_certificate`/`tls_ca`: the forwarder uses plaintext,
controller HTTPS uses a short-lived self-signed certificate (no
`controller_tls_private_key_pem`), and REST checks skip certificate
verification. Approved runs require certificates; `tls_certificate` and
`tls_ca` must be set together.

- an RFC 1918 /24 exercise network;
- unique, in-subnet target IPs and fully qualified host names;
- dedicated controller, domain-controller, workstation, and Splunk hosts;
- `FILE01` on `CTRL01` or a separate Linux host;
- required service checks, exact identity baseline, and run-correlated Splunk
  probes;
- no credential or secret fields in the manifest.

Validate the manifest and render an Ansible inventory only after it is
complete:

```sh
python3 citef-config/validate_environment.py validate \
  --config citef-config/environment.json
python3 citef-config/validate_environment.py inventory \
  --config citef-config/environment.json \
  > citef-config/inventory.ini
```

Install validator dependencies on the control host from the offline wheelhouse
with the same Python interpreter used for validation. `jsonschema` is declared
in `citef-config/requirements-validator.txt` and `shared/requirements.txt`;
confirm its wheel is in the bundle:

```sh
python3 -m pip install --no-index \
  --find-links offline-bundles/CITEF-RELEASE/netstrike-offline-bundle/destinations/CTRL01/wheelhouse \
  -r citef-config/requirements-validator.txt
```

For WinRM, install `pywinrm` from `citef-config/requirements-controller.txt`
the same way into the Python environment used by `ansible-playbook`.

The ignored generated inventory contains placeholders for every host (`test` /
`REPLACE_WITH_SECRET`; Windows also uses NTLM over HTTP, port 5985), not
approved credentials.
Replace them locally; for an existing manifest, set every Windows asset's
`port` to `5985` before rendering. Never put credentials in the manifest,
history, or repository. Inject SSH/WinRM credentials through approved Vault
or secret management, and `NETSTRIKE_READINESS_TOKEN`/`SPLUNK_TOKEN` into the
Ansible process environment. Each Splunk probe must include `{run_id}` and
return its configured `expected_event_id` to prove freshness and correlation.

For a standalone Windows telemetry run, you can override the inventory account
and have Ansible prompt for its password:

```sh
ansible-playbook \
  -i inventory.ini \
  playbooks/windows_telemetry.yml \
  --user 'DOMAIN\username' \
  --ask-pass
```

Alternatively, inject `ansible_user` and `ansible_password` from approved
secret storage. NTLM over HTTP is only for an isolated, approved management
network; otherwise use CITEF's approved WinRM transport and protection.

The checked-in example intentionally fails validation because its
range-owned configuration is incomplete. No inventory can be rendered from
it. CITEF approval is an operational prerequisite recorded in the
requirements/decision record; it is not duplicated as a manifest field.
The example and test addresses are not CITEF assignments.

## Offline provisioning and controller deployment

The manually triggered `Build offline bundle` workflow packages the
hash-verified Python runtime/wheelhouse, project sources, and pinned Ansible
collections. Its `inventory.json` records version, source, license, owner,
SHA-256, destination, and offline install method; resolve UNKNOWN license or
owner values before release. This build is not a complete transfer release:
stage approved Universal Forwarder/Sysmon installers, receiver CA, controller
TLS certificate/CA, and other external artifacts under
`offline_artifacts.directory`, then set their relative paths and SHA-256 hashes
in the local manifest. Licensed files remain Git-ignored. For example, stage
Sysmon at `sysmon/Sysmon.zip` and the Windows forwarder at
`windows/splunkforwarder-10.0.1-c486717c322b-windows-x64.msi`; Ansible verifies
hashes (including vendor SHA-512 for the forwarder) and Authenticode
signatures before installing. The Sysmon configuration is maintained in
`citef-config/files/sysmon-config.xml`; set its SHA-256 in the local manifest,
and Ansible verifies and copies that repository file directly. Sysmon's
extracted `Sysmon64.exe` is also signature-checked. See the
[offline bundle guide](../docs/offline-bundle.md).

Telemetry versions are Universal Forwarder 10.0.1 and Sysmon 15.22. CITEF
permits Universal Forwarder and HEC ingestion into a dedicated `netstrike`
index with one-day retention (relayed 2026-10-04). Separate participant
telemetry access from facilitator administration. The planned sources are
Windows event channels via Universal Forwarder and normalized project events
via HEC. The event ledger remains in local SQLite; HEC forwarding is not yet
implemented. Do not mark application-event telemetry ready until HEC/index,
access controls, and a run-correlated query are implemented and tested.

Download the pinned Ansible collections and dependencies on a connected
staging machine, transfer the tarballs through the approved offline path, and
install them on the Ansible control host without Galaxy access:

```sh
ansible-galaxy collection download \
  -r citef-config/requirements.yml \
  -p citef-config/collection-bundle
ansible-galaxy collection install \
  --offline \
  citef-config/collection-bundle/*.tar.gz \
  -p citef-config/collections
```

Run `ansible-playbook` from `citef-config/` to use its pinned config,
collections, roles, and local manifest. Before changing hosts, provisioning
verifies declared artifact hashes and bundle `SHA256SUMS`. The controller role
installs offline into an immutable, content-addressed release, then runs a
restricted systemd service as unprivileged `netstrike`, bound to CTRL01's
approved address and using staged HTTPS credentials (whose key/certificate
match is checked).

Inject `controller_service_tokens` (token-to-`actor_id`/`role` mapping),
`controller_readiness_token`, `controller_identity_audit_key` (32+ characters),
and `controller_tls_private_key_pem` through approved secret management. Trust
the controller TLS CA on clients and the Ansible host.

`controller_readiness_token` must be a key of `controller_service_tokens`, and
that entry must have `role: facilitator`; otherwise the role's assertions fail.
Define the token once and reference it so the two cannot drift:

```yaml
_ready: "<random-token>"   # e.g. openssl rand -hex 32
controller_readiness_token: "{{ _ready }}"
controller_service_tokens:
  "{{ _ready }}":
    actor_id: facilitator-1
    role: facilitator
```

By default the controller role reads the extracted bundle from
`<offline_artifacts.directory>/netstrike-offline-bundle`. To use a bundle
extracted elsewhere, set `controller_offline_bundle_root` to its absolute path
(the directory containing `runtime/` and `destinations/`), e.g.
`-e controller_offline_bundle_root=/path/to/offline-bundle/netstrike-offline-bundle`.

Keep this vars file out of git (or encrypt it with `ansible-vault`) and pass it
with `-e @secrets.yml`. Capture a clean snapshot
only after facilitator preparation and all external readiness gates pass.

Provision approved VMs from `citef-config/` with:

```sh
ansible-playbook \
  -i inventory.ini \
  playbooks/provision.yml \
  --extra-vars "deployment_id=UNIQUE_DEPLOYMENT_ID"
```

Provision only after independent review of the completed manifest, images,
artifacts, TLS materials, secrets, and CITEF approvals. Sample values are not
deployable; live provisioning and restore acceptance require the actual range.

## Post-restore readiness

Clean snapshots are the reset mechanism. Ansible validates restored hosts;
approved idempotent corrections are separate, versioned provisioning actions.
Ansible does not create VMs, control the hypervisor or snapshots, or provide
timed resets.

### Initial baseline and snapshot capture

Capture the initial clean baseline as a separate deployment: confirm images,
builds, addresses, access protocols, and bundle approval with CITEF; configure
approved VMs using offline automation; then pass service, identity, clock,
application, Splunk, network-policy, and emergency-stop checks. Never use
Internet repositories or commit licensed installers/secrets. The snapshot
owner records immutable snapshot IDs and passing evidence. Restore those
snapshots and pass readiness once before accepting the delivery baseline.

The repository's offline roles cover the proposed Ubuntu/Windows images,
DNS/NTP, AD/DNS, telemetry, and portal, but are only syntax-checked, not tested
on CITEF images. They are not hypervisor controls; claim acceptance only after
live image tests and restore cycles pass.

For each restore cycle:

1. Stop the scenario, archive its evidence, and confirm no registered action
   or prior-run process remains; retain prior evidence.
2. Have the named range operator restore every physical VM from its clean
   snapshot. On any failure, stop and escalate to Zian/Julien; no partial
   reset or participant admission.
3. Transfer the reviewed bundle and verify its manifest and SHA-256 at each
   destination. Generate a unique run ID and one harmless readiness event per
   required source.
4. Inject credentials through the approved mechanism and run:

   ```sh
   ansible-playbook \
     -i citef-config/inventory.ini \
     citef-config/playbooks/readiness.yml \
     --extra-vars "exercise_run_id=NEW_UNIQUE_RUN_ID"
   ```

   Readiness checks connectivity, OS mapping, internal DNS, clock skew,
   required services, AD users/groups, local application/event-ledger health,
   and run-correlated Splunk probes. It is read-only except for the emitted
   test events; secret-bearing API task output is suppressed.
5. Separately confirm network policy with the range operator. The manifest,
   playbook, and `/api/facilitator/readiness` check do not attest to egress;
   local readiness cannot replace Ansible/Splunk results, restore evidence,
   network-policy evidence, or facilitator sign-off.
6. Record snapshot IDs, readiness output, test-event IDs, bundle digest,
   operator, and outcome; facilitator signs before participant admission.
   Require three consecutive passing restore cycles. Any failure blocks
   admission and restarts the acceptance sequence after correction.

## Three-cycle acceptance record

Complete this table with actual evidence; do not mark a cycle passed from a
planned or simulated result.

| Cycle | Date/operator | Snapshot IDs / bundle digest | New run ID and telemetry probe IDs | Ansible result / blockers | Network-policy evidence | Facilitator sign-off |
|---|---|---|---|---|---|---|
| 1 | Pending | Pending | Pending | Pending | Pending | Pending |
| 2 | Pending | Pending | Pending | Pending | Pending | Pending |
| 3 | Pending | Pending | Pending | Pending | Pending | Pending |

The repository currently has no approved CITEF manifest or recorded CITEF
restore cycle. This is a proposed implementation and acceptance procedure,
not evidence that #103's external deployment criteria have passed.

## Local checks

The schema validator uses `jsonschema` from
`citef-config/requirements-validator.txt`; the cross-field checks use the
Python standard library. Install the requirement as described above, then run
the checks without range access:

```sh
python3 -m unittest discover -s citef-config/tests -v
```

Ansible syntax and live-target checks require the approved offline Ansible
runtime/collections and a complete local manifest. Do not validate by
connecting to guessed or example addresses.
