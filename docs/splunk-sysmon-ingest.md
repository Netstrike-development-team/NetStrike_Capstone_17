# Configure Splunk to receive Sysmon Windows events

This procedure configures the approved Splunk Enterprise receiver and verifies
Sysmon ingestion from the Windows endpoints. In the current topology,
`SPLUNK01` is supplied by the Cyber Range; do not install or modify Splunk
Enterprise there without the range administrator's approval. Keep all
credentials, private keys, and licensed installers outside Git.

## Configure the receiver

1. Confirm the approved Splunk Enterprise host is running version 10.0.1 and
   that the endpoint network can reach it on TCP 9997. In Splunk Web, open
   **Settings → Indexes → New Index**, create the configured Windows event
   index (the example manifest uses `netstrike`), and apply the approved
   retention and access-control settings.
2. Configure Splunk Enterprise to receive forwarder traffic on port 9997. In
   Splunk Web, use **Settings → Forwarding and receiving → Configure receiving
   → New Receiving Port**. Confirm the listener is enabled.
3. Configure port 9997 as a TLS-enabled Splunk TCP input, not a plaintext
   `[splunktcp://9997]` input. The receiving stanza in the receiver's
   `$SPLUNK_HOME/etc/system/local/inputs.conf` is:

   ```ini
   [splunktcp-ssl:9997]
   disabled = 0
   ```

   Install the approved receiver server certificate and CA chain, configure
   the TLS certificate settings required by the Splunk Enterprise 10.0.1
   `server.conf` reference and the Cyber Range's certificate requirements, and
   provide the matching trusted CA certificate to the forwarders. Do not change
   the forwarder to disable certificate verification. Avoid enabling a
   plaintext input on the same port.
4. Permit TCP 9997 from only the approved forwarder hosts. Apply the receiver
   configuration using the range's change process. Check that the
   receiver reports the port as listening and that the index is searchable
   before installing or testing forwarders.

The Windows forwarder's TLS output is rendered from
[`outputs.conf.j2`](../citef-config/roles/windows_telemetry/templates/outputs.conf.j2).
The event-channel inputs are rendered from
[`inputs.conf.j2`](../citef-config/roles/windows_telemetry/templates/inputs.conf.j2);
they collect Security, PowerShell Operational, and Sysmon Operational events
into the configured Windows index. The receiver host, index, certificates, and
approved target inventory must come from the completed local
`citef-config/environment.json`, not the sample values.

## Configure and test Windows forwarding with Ansible

The `windows_telemetry` role in `citef-config/playbooks/provision.yml` stages
the approved Universal Forwarder MSI and Sysmon ZIP, verifies the staged
artifact hashes and signatures, installs/configures both products offline,
enables the Windows event channels, configures TLS-verified forwarding, and
starts the services. Put each artifact in the approved offline-artifact
directory and complete the manifest entries with the exact staged filenames
and SHA-256 values before provisioning. The manifest also records and verifies
the published Universal Forwarder SHA-512 checksums for both the Linux DEB and
Windows MSI.

After provisioning, run the purpose-built ingestion check with a new run ID.
It creates a harmless `cmd.exe` process marker on each approved Windows host,
confirms that Sysmon recorded Event ID 1 locally, then searches Splunk for that
host's marker in the configured index and Sysmon event source.

```sh
read -rsp 'Splunk API token: ' SPLUNK_TOKEN
printf '\n'
export SPLUNK_TOKEN
ansible-playbook \
  -i citef-config/inventory.ini \
  citef-config/playbooks/test_sysmon_ingest.yml \
  --extra-vars "exercise_run_id=sysmon-ingest-$(date -u +%Y%m%dT%H%M%SZ)"
unset SPLUNK_TOKEN
```

Run this from the repository root after populating the approved manifest,
inventory, Ansible runtime/collections, and TLS trust files. The token needs
permission to search the configured Windows index. The playbook suppresses
task output containing the token or search response. A successful run verifies
local Sysmon event generation and arrival in Splunk for each Windows endpoint;
it does not establish retention, role separation, licensing approval, or full
range readiness.

## Troubleshooting

- **No local Event ID 1:** Check the `Sysmon64` service, the
  `Microsoft-Windows-Sysmon/Operational` channel, and the applied Sysmon XML
  configuration before debugging forwarding.
- **Local event exists but no Splunk result:** Check the `SplunkForwarder`
  service, the active receiver in `splunk.exe list forward-server`, TCP 9997
  reachability, TLS certificate trust, and `splunkd.log` on the forwarder and
  receiver.
- **Forwarder connects but no event appears:** Confirm `inputs.conf` has the
  Sysmon Operational stanza enabled, the configured Windows index exists, and
  the search role can read it. Search a wider recent time range and verify the
  host and source values in Splunk.
- **TLS errors:** Verify receiver certificate names/CA chain and the staged CA
  file. Do not turn off certificate validation or bypass the approved
  certificate process.
