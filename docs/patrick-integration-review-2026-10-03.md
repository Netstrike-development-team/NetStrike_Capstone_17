# Patrick integration review — October 3, 2026

Reviewed current open PRs, not merged deployment or acceptance evidence:

- [#127](https://github.com/Netstrike-development-team/NetStrike_Capstone_17/pull/127),
  `issue/103-ansible-config`, inspected at `d5781cb9eb962c7515a36ecfdd82c516517c42a6`.
- [#128](https://github.com/Netstrike-development-team/NetStrike_Capstone_17/pull/128),
  `issue/101-offline-bundle-ansible`, inspected at `c8406ba`.
  It includes the provisioning commits; #127 should land first, then #128 should
  be refreshed/reviewed against the updated dev base so overlapping changes are
  not mistaken for independent bundle additions. Neither is merged by this review.
  Earlier #124/#125/#126 are closed, not the current integration PRs.

## What Patrick added

1. An intentionally incomplete, non-secret environment manifest plus JSON Schema
   and cross-field/network validator; approved values can generate inventory.
2. Proposed dedicated DC01/FIN-WS01/SPLUNK01 VMs with controller-managed mock
   identity/helpdesk/cloud/file services on CTRL01. Network/image values are
   planning assumptions, not approved range allocations.
3. Offline Ansible provisioning for Windows AD/DNS/internal time, synthetic
   domain/users/group baseline, domain membership, Linux DNS/NTP, Windows UF and
   Sysmon, Linux UF, and a HTTPS portal systemd service under `netstrike`.
4. Artifact hash gates, injected-secret/TLS handling, OS/service/DNS/clock/fixture
   checks, local portal readiness, run-correlated Splunk probes and explicit
   human egress/emergency-stop/snapshot acceptance records.
5. Expanded offline bundling: dashboard/controller dependencies, module/shared/
   orchestrator/schema/dashboard/Ansible source, pinned collection tarballs and
   metadata, and local dependency/collection installation verification.

Local non-deploying validation of the current #128 tree: **33 tests passed**
(16 environment-manifest tests plus 17 offline-bundle tests). No installer,
Ansible provisioning, range VM, Splunk service or offline Actions build was run
by this review. Passing unit tests/CI are not clean-VM deployment evidence.

## Application interfaces and next Aya scope

The proposed unit uses `/opt/netstrike/current`, Python/uvicorn under
`/opt/netstrike/venv`, persistent SQLite at `/var/lib/netstrike/portal.sqlite3`,
existing token/audit/origin configuration and authenticated local readiness.
Its deployment fixture is identity-only; full-play selection still needs an
explicit approved configuration/rehearsal, not an assumption that all stages
are enabled just because their source is bundled.

The Linux UF currently monitors system/auth logs, not the SQLite ledger. #127
explicitly leaves normalized application-event forwarding for another task.
Aya's #129 provides a protected incremental JSONL monitored-file **exporter** in
the already-bundled `dashboard/` tree. It does not edit these PRs, configure the
forwarder/Splunk, provision a VM or take over Patrick's scheduling/acceptance.
See [the exporter handoff](event-spool.md).

## Two likely deployment blockers to check before merging/deploying #127

- `roles/controller_service/tasks/main.yml` defines a unique
  `/opt/netstrike/releases/<deployment>-<source-digest>` destination, creates its
  parent `/opt/netstrike/releases`, but does not create that release destination
  before `ansible.builtin.unarchive` uses it. The intended release directory
  needs to exist with reviewed ownership/mode before extraction, as required by
  the [Ansible unarchive contract](https://docs.ansible.com/projects/ansible-core/devel/collections/ansible/builtin/unarchive_module.html).
  Validate this
  on a genuinely clean target rather than an already-populated development VM.
- The TLS key is installed root-owned `0600`, while
  `templates/netstrike-portal.service.j2` runs uvicorn as `User=netstrike` and
  supplies that key through `--ssl-keyfile`. The process needs tightly scoped
  read access to the key and traversal access to `/etc/netstrike` (currently
  root-owned `0700`). Do not solve it by running the portal as root or making
  secrets public; Patrick should choose and test a dedicated group/credentials
  mechanism and appropriate directory/file access on the range baseline.

These are code-based findings, not observed live VM failures, and this review
has not modified Patrick's branches. Source-to-bundle layout, compatible images,
Ansible/TLS/offline installation, UF ingestion and actual restore cycles still
need Patrick's clean-target verification and recorded range approval.
