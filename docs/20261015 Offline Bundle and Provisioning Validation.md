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
file, secrets file, a test deployment ID, and `external-ntp=true`:

```sh
./provision.sh <offline-bundle.tar.gz> offline-bundles.tar.gz \
  environment.json secrets.yml <deployment-id> true
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

See the [video demonstration](20261015%20Offline%20Bundle%20and%20Provisioning%20Validation.mkv).
