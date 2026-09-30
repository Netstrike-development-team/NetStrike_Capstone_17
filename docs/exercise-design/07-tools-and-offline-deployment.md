# Tools, Licensing, and Air-Gapped Deployment Plan

**Status:** Proposed response to the Cyber Range request of September 24, 2026

**Owners:** Aya (application choices), Patrick (Splunk/environment validation), Ashley (client confirmation)

## Tool decisions

| Purpose | MVP choice | License or responsibility | Air-gapped approach |
|---|---|---|---|
| Cyber Range VMs | Cyber Range-provided Windows 11, Windows Server, and Linux amd64 images | Cyber Range owns image/evaluation-license compliance | Create the topology directly in the platform; no runtime Internet required |
| SIEM | Cyber Range-provided Splunk Enterprise | Cyber Range-provided educational license; exact version and meaning of the stated 10 GB limit must be confirmed | Install/configure locally; send Windows events through Universal Forwarder and project events through HEC or a monitored file |
| Windows endpoint telemetry | Microsoft Sysmon plus Windows Security and PowerShell audit logs | Microsoft/Sysinternals terms; Cyber Range approves the binary and configuration | Pre-stage the signed Sysmon binary and XML configuration, then install through Ansible/PowerShell |
| EDR | No commercial EDR in the MVP | No additional EDR license required | Sysmon supplies evidence and NetStrike safe actions simulate the narrow containment controls required by the exercise |
| Windows log transport | Splunk Universal Forwarder | Covered by the Cyber Range's approved Splunk deployment and terms | Pre-stage the matching MSI and install silently with a least-privileged collection account where practical |
| Controller/API | Python 3.11, FastAPI, Uvicorn, Pydantic | Open-source dependencies; FastAPI is MIT licensed | Pin versions and transfer a wheelhouse with hashes; install with `pip --no-index` |
| State/event ledger | Python `sqlite3`/SQLite | Included with Python/public-domain SQLite | Ships with the controller; no network service required |
| Portal | Server-rendered HTML/CSS/JavaScript, with Jinja templates if needed | Project code and open-source Python dependency | Bundled with the controller; no CDN or external fonts/scripts |
| Configuration | `ansible-core`, `ansible.windows`, PowerShell, SSH/WinRM | Open-source Ansible components plus built-in OS tools | Download pinned Ansible collections and Python wheels in advance and transfer them with checksums |
| Mock cloud | Project-owned Python state model | Project code | Runs locally on `CTRL01`; no AWS, LocalStack, or Internet required |
| Impact/recovery | Project-owned marker and reversible-move fixtures | Project code | Operates only in a run-specific allowlisted directory; no encryption tool required |
| Development CI | GitHub Actions | Development-only hosted service | Not required inside the delivery environment; release test evidence travels with the bundle |

## EDR clarification

The MVP does not claim to deploy a production EDR. Adding Microsoft Defender
for Endpoint or another commercial platform would add licensing, cloud, and
integration risk without being necessary for the five learning objectives.

Endpoint investigation uses Sysmon, Windows auditing, PowerShell logs, and
Splunk. Endpoint isolation and remediation use narrow, allowlisted NetStrike
actions whose state is visible to the controller. The participant and staff
guides will label those controls as exercise controls.

If the Cyber Range specifically requires a named EDR product, it must confirm
the product, evaluation terms, offline capability, image compatibility, and
available support before it is added to the MVP.

## Offline release bundle

Patrick owns the bundle inventory and validation; Aya supplies application
artifacts. The bundle will contain:

1. a versioned source/release archive and checksum manifest;
2. pinned Python wheels and a locked requirements file;
3. pinned Ansible collection archives and `requirements.yml`;
4. approved Sysmon binary and configuration;
5. a Splunk Universal Forwarder installer matching the range's Splunk version;
6. Splunk app/configuration containing inputs, field mappings, searches, and dashboards;
7. Ansible inventory templates and configuration playbooks;
8. synthetic fixtures, fallback evidence, and known-good file manifests; and
9. install, readiness, removal, and known-limitations documentation.

Licensed installers and Cyber Range-specific secrets are transferred through
the approved file-push mechanism and are not committed to Git.

## Acceptance checks

- Every version and checksum in the bundle is recorded.
- Installation succeeds with network access disabled.
- No page or service depends on a CDN, external API, public package index, or public cloud.
- Every VM reports correct DNS and time before a run.
- Each expected data source appears in Splunk and stays below the confirmed license limit.
- A clean snapshot restore followed by readiness validation produces the documented baseline.
- Reinstall and restore instructions are tested by someone other than the artifact author.

## References

- [Microsoft Sysmon documentation](https://learn.microsoft.com/en-us/sysinternals/downloads/sysmon)
- [Splunk Windows Universal Forwarder installation](https://help.splunk.com/en/data-management/forward-data/universal-forwarder-manual/9.1/install-the-universal-forwarder/install-a-windows-universal-forwarder)
- [Splunk HTTP Event Collector setup](https://help.splunk.com/en/splunk-enterprise/get-started/get-data-in/9.3/get-data-with-http-event-collector/set-up-and-use-http-event-collector-in-splunk-web)
- [Ansible offline collection download and installation](https://docs.ansible.com/projects/ansible-core/2.13/user_guide/collections_using.html#downloading-collections)
- [FastAPI license](https://github.com/fastapi/fastapi#license)
