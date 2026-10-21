# Offline bundle and provisioning validation — 2026-10-21

**Operator:** Patrick  
**Scope:** Local provisioning, telemetry, and restore rehearsal; not CITEF
deployment acceptance.

## Final layout and environment

- `ANSIBLE01` and `CTRL01` are Ubuntu Server 26.04.1 LTS amd64 VMs.
- `FILE01` is the logical file/fixture service on `CTRL01`, not a separate VM.
- `DC01` is Windows Server 2025 Evaluation Version, build 26100.32230.
- `FIN-WS01` is Windows 11 Pro 26H2, build 2300.9457.
- `SPLUNK01` is supplied by the Cyber Range. Local rehearsal used Docker-hosted
  Splunk rather than an independently managed Splunk VM.
- Use the addresses, DNS, NTP, and management paths recorded in the
  [network diagrams](network-diagram.puml) and the corresponding
  [local diagram](network-diagram-local.puml); the local rehearsal values are
  not range assignments.

The offline bundle contains its application dependencies, so provisioning is
not tied to a particular available OS image. The team has its own ISO images if
needed; coordinate image selection with Zian/Julien for the range.

## Preparation and transfer

- Switched the Windows VM network to Private and enabled WinRM with
  `winrm quickconfig` as administrator. Set root passwords on the Linux VMs
  using `sudo passwd root`.
- Capture the clean snapshot after each target has its OS installed and remote
  management configured (SSH/WinRM), but before running the Ansible playbook.
  This preserves the management path while keeping Ansible-applied baseline
  and telemetry configuration out of the clean starting point. This replaces
  the earlier assumption that snapshots follow baseline and telemetry checks.
- Simulated an air gap by blocking DNS requests going out to the Internet.
  This is not a full Internet-egress isolation test and does not establish the
  Cyber Range network policy.

Download the offline bundle from GitHub and transfer it by USB to the designated
Ansible host. Copy `secrets.example.yml` to a private secrets file, fill in the
approved values, and pass that file to `provision.sh`. Keep credentials out of
Git, screenshots, logs, and issue comments. The local rehearsal used `scp`;
USB is the planned range transfer method.

For this rehearsal, the licensed Sysmon and Universal Forwarder installers
were packaged in `offline-bundles.tar.gz`; `local.environment.json` and the
private secrets file were prepared from their examples and adapted to the
personal network and Docker-hosted Splunk.

The script was run with the offline bundle, licensed-artifact archive,
environment file, private secrets file, a test deployment version, and a test
exercise run ID:

```sh
./provision.sh <offline-bundle.tar.gz> offline-bundles.tar.gz \
  environment.json secrets.yml <deployment-version> <exercise-run-id>
```

Credentials were test-only; literal values are intentionally omitted.

## Results and limitations

- The Ansible recap succeeded for `CTRL01`, `DC01`, and `FIN-WS01`. The
  `SPLUNK01` unreachable result is expected in this local setup: Splunk ran in a
  Docker container rather than as a separately managed VM. The first supplied
  screenshot records the play recap.
- Windows hosts joined the exercise domain and used DC01 for DNS/NTP. The
  portal passed its startup readiness checks.
- Splunk search of `index="netstrike"` showed telemetry from `CTRL01`, `DC01`,
  and `FIN-WS01` with `run_id=test2-2026-10-21`; the second supplied screenshot
  shows the events and run ID.
- Snapshot restore and provisioning/readiness were successfully exercised
  three times, but not in consecutive cycles. The shared test hardware (six
  cores and 32 GB RAM for four VMs plus Splunk) caused instability and
  multi-minute provisioning delays. The consecutive-cycle acceptance criterion
  is therefore not demonstrated.
- The Ansible `readiness.yml` playbook checks deployment readiness, and portal
  startup performs its own local preflight/readiness gate. A failed startup
  check prevents the application from starting; actionable blocker evidence is
  available in the logs. Neither local check alone certifies Cyber Range
  network policy or authorizes participant admission.
- The range operator performs hypervisor snapshot restoration; Patrick
  coordinates the exercise restore/readiness workflow. Escalate an unavailable
  or failed restore/readiness result to Zian/Julien and do not admit
  participants.
- The local DNS-blocking exercise is not a full Internet-egress isolation test.
  Local addresses, Docker-hosted Splunk, and these results do not establish
  Cyber Range deployment acceptance.

# Offline bundle and provisioning validation — 2026-10-15

**Operator:** Patrick  
**Scope:** Local provisioning rehearsal on the configured test VMs; not CITEF
deployment acceptance.

## Environment and preparation

- Created a Windows 11 26H2 `FIN-WS01`, an Ubuntu 26.04.1 `CTRL01`, and a
  separate Ubuntu 26.04.1 Ansible host. Personal-LAN addresses and the local
  environment manifest are intentionally not recorded here.
- Used existing personal-network DNS and NTP services instead of `DC01`.
- Switched the Windows VM network to Private and enabled WinRM with
  `winrm quickconfig` as administrator. Set root passwords on the Linux VMs
  using `sudo passwd root`.
- Captured snapshots of the blank VM states. This run did not test restoring
  those snapshots.
- Simulated an air gap by blocking DNS requests going out to the Internet.
  This is not a full Internet-egress isolation test and does not establish the
  Cyber Range network policy.

## Offline transfer and provisioning

Downloaded the CTRL01 offline bundle and `scripts/provision.sh` from GitHub,
packaged the licensed Sysmon and Universal Forwarder installers in
`offline-bundles.tar.gz`, and prepared local `environment.json` and `secrets.yml`
from the example files. The environment values were adjusted for the personal
network and Docker-hosted Splunk. The files were copied to the Ansible host with
`scp`; USB is the planned transfer method in the Cyber Range.

Ran the script with the offline bundle, licensed-artifact archive, environment
file, secrets file, a test deployment version, a test exercise run ID, and `external-ntp=true`:

```sh
./provision.sh <offline-bundle.tar.gz> offline-bundles.tar.gz \
  environment.json secrets.yml <deployment-version> <exercise-run-id> true
```

The credentials were test-only and supplied through the local secrets file;
their literal values are intentionally omitted from this record and the linked
GitHub issue comments.

## Result and limitations

- The Ansible summary reported two host failures, for `DC01` and the Splunk
  Server. Neither host was being configured in this test; these results do not
  establish that either host was provisioned or ready.
- Ansible warnings caused by use of `su` were reported as harmless.
- The test used existing network DNS/NTP and did not exercise `DC01`, Splunk
  Server configuration, full Internet-egress blocking, or snapshot restoration.
  It is therefore a scoped provisioning rehearsal, not proof of full offline
  readiness, telemetry acceptance, or restore acceptance.
