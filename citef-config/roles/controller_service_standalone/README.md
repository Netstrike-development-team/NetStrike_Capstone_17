# Standalone controller service role

Run this role from an Ansible execution host against a provisioned Linux
controller with Python, `tar`, `sha256sum`, OpenSSL, systemd, SSH access and
privilege escalation. The controller needs sufficient free space for the bundle
and extracted files. This role does not install or configure the Splunk forwarder.

Provide:

- The CI-built `netstrike-CTRL01-*.tar.gz` on the Ansible host, as
  `controller_bundle_archive`. Verify its provenance independently: its
  `SHA256SUMS` detects corruption, not authenticity.
- An environment variables file such as `environment.json` based on
  [`environment.example.json`](../../environment.example.json), with
  `controller.listen_port`, `controller.readiness_url` and a nonempty
  `controller.sso_allowed_origins` array. The readiness URL's hostname must
  identify the controller.
- A private secrets file containing `controller_service_tokens` (token-to-actor
  and role mapping), `controller_readiness_token` (a matching facilitator token,
  at least 32 characters) and `controller_identity_audit_key` (at least 32
  characters). See [`secrets.example.yml`](../../secrets.example.yml) and the
  [portal deployment contract](../../../docs/deployment/application-deployment-contract.md).
  Supply connection and privilege-escalation credentials privately as needed.
- `deployment_version` and `exercise_run_id`: 8-64 path-safe letters, digits,
  dots, underscores or hyphens, beginning with a letter or digit. The run ID
  must match the forwarders' run ID and must not have been used for a previous
  portal start.

For example, save this as `citef-config/playbooks/standalone-controller.yml`:

```yaml
---
- hosts: all
  gather_facts: false
  become: true
  vars_files:
    - ../environment.json
  vars:
    ansible_host: "{{ inventory_hostname }}"
  roles:
    - controller_service_standalone
```

From `citef-config/`, substitute your target and archive path and run:

```sh
ansible-playbook -i 'CONTROLLER_IP,' playbooks/standalone-controller.yml \
  -e @/private/path/secrets.yml \
  -e controller_bundle_archive=/absolute/path/netstrike-CTRL01-RUN_ID.tar.gz \
  -e deployment_version=release-001 \
  -e exercise_run_id=exercise-001
```

The role stages and extracts the archive on the controller, verifies its
checksums, deploys from it and removes the temporary staging directory even on
failure when the controller remains reachable. `controller_scenario_scope`
defaults to `full-play` and can be set to
`identity` or `cloud`; `controller_recovery_mode` defaults to `fixture`.
`event_spool_group` defaults to `netstrike-staff`.

For supplied TLS, set both `controller.tls_certificate.file` and
`controller.tls_ca.file` relative to the execution host's
`playbook_dir/../../<offline_artifacts.directory>/`, and supply the PEM
`controller_tls_private_key_pem` in the private secrets file. Verify the TLS
files independently before deploying. Without a certificate the role generates
a self-signed certificate for testing only. An already-running portal retains
its start-time configuration; use a clean snapshot and new run ID to apply
changes.
