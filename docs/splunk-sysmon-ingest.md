# Configure Splunk to receive Sysmon Windows events

This guide covers receiver prerequisites and the Windows Sysmon ingestion
check. The Cyber Range supplies `SPLUNK01`; the team controls exercise receiver,
index, role, and search configuration under delegated authority within the
recorded license/capacity limits. No additional per-change configuration approval
is outstanding; involve Zian/Julien for platform assistance or escalation, not a
new permission gate. Keep credentials, private keys, and
licensed installers outside Git.

## Receiver prerequisites

Configure and validate the receiver as exercise staff. The current manifest requires Splunk
Enterprise 10.0.1, a Windows event index, and TCP 9997. In Splunk Web, create
the configured index under **Settings → Indexes** and apply approved retention
and access controls. Configure receiving under **Settings → Forwarding and
receiving**. Allow TCP 9997 only from approved forwarders; confirm the listener
and searchable index before testing.

Configure port 9997 as a TLS-enabled Splunk TCP input, not plaintext:

```ini
[splunktcp-ssl:9997]
disabled = 0
```

Install the approved server certificate and CA chain, configure the TLS
settings in the receiver's `server.conf` as required by Splunk 10.0.1 and range
policy, and stage the matching trusted CA on each forwarder. Never disable
certificate verification or enable a plaintext input on the same port.

Use the completed local `citef-config/environment.json` for receiver, index,
certificate, and target values; do not use sample addresses. The Windows role
renders its output and event inputs from
[`outputs.conf.j2`](../citef-config/roles/windows_telemetry/templates/outputs.conf.j2)
and [`inputs.conf.j2`](../citef-config/roles/windows_telemetry/templates/inputs.conf.j2).
**The current Windows output template sets `useSSL = false`; its CA and server
verification settings are commented out, as are the role's CA-staging tasks.
It therefore does not meet the TLS receiver requirements above. Do not use it
for an approved TLS-required deployment until the template and role are updated
and verified.** Its inputs collect Security, PowerShell Operational, and
Sysmon Operational events into the configured Windows index.

## Provision Windows forwarding

The `windows_telemetry` role stages the approved Universal Forwarder MSI and
Sysmon ZIP and installs them offline. It verifies the MSI's SHA-512 and
Authenticode signature, and the Sysmon ZIP/configuration SHA-256 values and
extracted executable signature. Stage exact filenames in the approved
offline-artifact directory and complete the manifest with SHA-256 values.
Artifact validation also checks published Universal Forwarder SHA-512
checksums for both the Linux DEB and Windows MSI.

On fresh Windows hosts, `LAUNCHSPLUNK=0` prevents early startup. After
configuration, a single deduplicated handler starts the forwarder or restarts
it once if changed; unchanged runs do not restart it. Each service transition
has a 120-second timeout, and failures stop provisioning.

Use the current `provision.sh` workflow in the
[`citef-config` README](../citef-config/README.md) to install the offline
runtime/collections, generate `inventory.ini`, and provision from the extracted
bundle source. Then run the purpose-built test from that generated
`source/citef-config` directory. It creates a harmless `cmd.exe` marker on each
approved Windows host, confirms local Sysmon Event ID 1, and searches the
configured index and Sysmon event source for each unique host marker.

```sh
cd offline-bundle/netstrike-offline-bundle/source/citef-config
export BUNDLE_ROOT="$(cd ../.. && pwd)"
read -rsp 'Splunk API token: ' SPLUNK_TOKEN
printf '\n'
export SPLUNK_TOKEN
"$BUNDLE_ROOT/python/bin/ansible-playbook" \
  -i inventory.ini \
  playbooks/test_sysmon_ingest.yml \
  --extra-vars "exercise_run_id=sysmon-ingest-$(date -u +%Y%m%dT%H%M%SZ)"
unset SPLUNK_TOKEN
```

Use a new run ID for each test. Run Ansible from this directory so
`ansible.cfg` finds the installed collections. If inventory is missing, generate
it with `python3 validate_environment.py inventory > inventory.ini` from
`source/citef-config`; an absent or empty `[windows_hosts]` group causes the
playbook to fail. The search token needs access to the configured Windows index.
The playbook suppresses output containing the token or search response. A
successful test establishes local event generation and Splunk arrival for each
Windows endpoint only—not retention, access separation, licensing approval, or
range readiness.

## Troubleshooting

- **No local Event ID 1:** Check `Sysmon64`, the
  `Microsoft-Windows-Sysmon/Operational` channel, and the applied Sysmon XML.
- **Local event exists but no Splunk result:** Check `SplunkForwarder`,
  `splunk.exe list forward-server`, TCP 9997 reachability, certificate trust,
  receiver/forwarder `splunkd.log`, and the configured index, host, and source.
- **Forwarder connects but events are missing:** Confirm the Sysmon input stanza
  is enabled and the Splunk search role can read the configured index; widen the
  time range and check host/source values.
- **TLS errors:** Verify receiver certificate names and CA chain and the staged
  CA file. Do not disable validation or bypass the approved certificate process.

The October 2026 local rehearsal used Docker-hosted Splunk, not the
Cyber-Range-managed receiver. It does not validate range network policy or
establish Cyber Range deployment acceptance; see the
[provisioning validation report](offline-bundle-provisioning-validation.md).

For TLS REST searches, configure the receiver CA in the manifest; the test
validates the certificate only when that CA is configured. Approved deployments
must use their required TLS material.
