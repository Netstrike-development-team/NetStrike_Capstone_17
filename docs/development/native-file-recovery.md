# Native file recovery: application implementation and range handoff

Owner: Aya (application); tracking issue #198, supporting #83. Added after the
November 17 technical-meeting review. Feature branches target `dev`.

## What changes for participants

`NETSTRIKE_RECOVERY_MODE=native_files` makes the portal an observer of a small
file-recovery task. Participants restore the five synthetic business files with
ordinary file tools against the **same live directory the controller observes**.
The participant portal cannot copy the files for them. Its **Verify restored
files** action reads the actual files and records whether their SHA-256 values
match the protected expected manifest and whether the backup/staged originals
remain intact. There is no learner-supplied success flag or filesystem path.

The portal still delivers messages and records evidence, questions and the final
brief. Splunk remains the intended primary investigation tool. Identity/AD,
endpoint isolation and public-cloud behavior remain simulated in this change.

The default `fixture` mode preserves existing demos and branch rehearsals. It
offers the original portal restore action; it is explicitly labelled as fixture
demo mode. Native mode requires full play and must be selected before startup.
It survives application reset; new runs never inherit old verification IDs.

## What is verified, and what is not

| Observation | Current implementation |
|---|---|
| Actual restored file contents | Five run-scoped live files match the server's expected SHA-256 manifest. |
| Backup integrity | Backup bytes match the expected manifest; a corrupt backup cannot be legitimized by copying it. |
| Preserved originals | Staging is empty or contains the complete unchanged original set. |
| Incident artifacts | Marker files and the harmless note can remain for evidence preservation. Verification never deletes them. |
| Current evidence | Verification event belongs to the current run; final review re-reads the files and requires the recorded live manifest still to match. |
| Verification writes | None to the fixture. The existing action/event ledger records the request and observation. |
| Who restored files / which tool | **Not verified.** File state does not prove learner attribution. |
| Windows ACLs / backup read-only access | **Not verified.** The verifier reads in the controller's OS identity, not the learner's Windows identity. |
| Intended-user usability | **Not verified.** The intended user must separately open the files through the delivered access path. |
| Full service recovery / live Splunk | **Not established** by the file check or local automated smoke. |

The canonical observation is `recovery.files.verified` with
`verification_method=controller_read_only_filesystem`, run/request identifiers,
hashes, checks and explicit false values for unverified permissions/access and
attribution. It appears in the participant's recovery audit and staff canonical
exports. It is **not** projected as a simulated `backup.restore.completed`
receipt into the learner Splunk feed: that would imply the portal performed the
restore. Standard host/file-access telemetry and intended-user evidence must be
validated separately in the range. The two existing Splunk feeds and RBAC are
unchanged.

The final review's automatic observations remain a limited developer signal.
Anna's human rubric must assess backup selection, preservation, containment,
permission/usability checks, reasoning and communication; matching bytes alone
do not establish the complete learning objective.

## Run a free local developer demonstration

From the repository root, using an environment with `dashboard/requirements.txt`
installed:

```bash
python -m orchestrator.impact_demo --outcome realized --recovery-mode native_files --execute
```

This compressed automated developer persona creates a temporary disposable run,
reaches marker-only impact, copies the known-good files with `/bin/cp`, requests
read-only verification, submits a synthetic brief and completes play. The
temporary files are removed afterward. It does not launch a persistent server,
need a VM, contact the Internet or use a paid product.

Expected summary: `recovery_mode` is `native_files`, `available_before_recovery`
is 0, `recovery_observations_passed` is true, `play_state` is `completed` and
`windows_access_verified` is false. `baseline_restored` is **false** because
incident markers and staged originals remain preserved. This is intentional:
learner recovery and staff cleanup/reset are different operations.

For HTTP and fault checks:

```bash
python -m pytest dashboard/tests/test_native_recovery.py dashboard/tests/test_configuration.py dashboard/tests/test_packaged_journey.py -q
node --test dashboard/tests/participant_session.test.mjs
```

With the pinned developer browser tooling and managed Chromium installed, run
the five-step actual-browser native recovery journey:

```bash
python scripts/native_recovery_browser_smoke.py --execute --output /tmp/netstrike-native-browser-new
```

Use a new output directory each time. This captures the actual native-mode UI,
OS copy, verification, brief, completed run/export and reset. It uses the shared
loopback/server/browser cleanup harness and runs strictly in the existing browser
CI job alongside the two original journeys. It does not use mocked API replies,
record a learner grade, or establish Windows access. The output directory retains
screenshots, the current-run JSONL ledger and a source-correlated receipt.

The actual packaged Linux offline smoke now starts a second fresh application in
native mode, denies portal restore and incomplete verification, uses `/bin/cp`,
verifies the files, submits the brief, completes play, exports, resets and checks
that the mode/archive survive. Its receipts are under `native-recovery/` beside
the original fixture-mode smoke. This exercises actual packaged application
HTTP routes and publications; it is still an automated local test.

## Configure the application

Set the existing full-play configuration and:

```text
NETSTRIKE_RECOVERY_MODE=native_files
```

The Ansible controller role accepts `controller_recovery_mode: native_files` and
renders this setting. It defaults to `fixture` until native file access has been
prepared and tested. Preflight rejects unknown modes and native mode on an
identity/cloud-only scenario before database or fixture construction. Its safe
report states the selected mode and warns that external access checks remain.
This switch does not configure a share or grant OS permissions.

For one run, the controller's private backing paths are:

```text
NETSTRIKE_IMPACT_ROOT/<run_id>/live        designated recovery destination
NETSTRIKE_IMPACT_ROOT/<run_id>/known-good  trusted backup source
NETSTRIKE_IMPACT_ROOT/<run_id>/staging     controller-only preserved originals
```

Do **not** give participants the controller account, shell, database, tokens,
application directory, the whole impact root or the whole run directory. All
parents and staging remain controlled by staff. Only the exact live directory
is writable through the agreed learner access path; the exact known-good
directory is read-only. Parent replacement, links and access to other runs must
be prevented by the OS/share configuration. The verifier rejects unsafe or
changing entries but does not create an OS authorization boundary itself.

## Patrick's concrete deployment and acceptance checklist

1. Choose the learner path: for example, two narrowly scoped SMB shares backed
   by the Linux controller's **current run** directories, accessible from the
   Windows workstation. Another approved file-transfer/native-tool path is
   possible. Provision the server/packages and access with Ansible/offline
   artifacts. No actual share is installed by this application PR.
2. Keep staff ownership of all directory parents, backup and staging. Grant
   participant write access only to the live directory, read-only access only
   to the backup. Do not follow symlinks or allow access outside the shares.
   Avoid a broadly privileged service/forced-user account or broad recursive
   chmod. Preserve a staff management path. Record exact identities and ACLs.
3. Verify as the **actual learner** that the live path can be written and the
   backup cannot be changed/deleted. Verify that staging, parent folders,
   secrets and another run cannot be reached. A portal token is not an OS login.
4. Set `controller_recovery_mode: native_files`, provision a fresh shared run
   ID, and confirm preflight, readiness, UI mode and all host run tags. Retain
   the deployed revision, bundle hash and concrete learner paths in the record.
5. Reach the recovery stage. Preserve relevant evidence before copying. Restore
   the five supplied files with File Explorer or PowerShell and leave the
   harmless markers/note untouched. Verify both partial and complete restores.
6. Compare hashes, inspect ACLs and open the restored files as the intended
   business user. Record this separately from the controller's hash observation.
   Include a readable-by-controller / denied-to-business-user negative case.
   Such a case must not receive full human recovery credit.
7. In the portal, enter the fixture identifier from the evidence, uncheck
   **Preview only** and click **Verify restored files**. Refresh the recovery
   audit, retain its event ID and cite it in the final brief along with the
   separate permission/usability checks and any remaining limitations.
8. Confirm canonical observation forwarding in staff Splunk, then correlate
   actual available file/share/PowerShell host logs with the shared run ID.
   Ensure participant Splunk access still excludes staff control/rubric data.
9. Stop/finish and export outside all VMs that will be reverted. Disconnect or
   revoke old-run file access before application cleanup or snapshot restore.
   Verify the old backup is unchanged, staff reset restores the disposable
   baseline and a new run grants no access to the old run's folders. Rebind
   exact shares with the clean snapshot/reprovision/shared-new-ID procedure.

Do not enable native mode for participants until this access path is tested.
If a step fails, record an environment/platform issue, not a learner failure.
Aya fixes application defects found by these checks; #83/#104 remain open for
live acceptance. A real AD account task is a separate optional enhancement.

## Anna and Ashley

Anna aligns the task, solution guide and rubric with the concrete tools and paths
Patrick validates. Describe evidence preservation before restore; distinguish
file hashes, permissions and usability. Do not give learners the exact solution
sequence above as a graded task or count the automated developer persona as an
independent learner rehearsal. Ashley coordinates the client review, dates and
accepted limitations. Exercise timing remains 15 + 130 + 25 minutes.

Tool references: Microsoft's [Copy-Item](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/copy-item?view=powershell-5.1),
[Get-FileHash](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-filehash?view=powershell-5.1)
and [Get-Acl](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.security/get-acl?view=powershell-5.1).
These document the tools; the actual range mapping and permission tests are still
required.
