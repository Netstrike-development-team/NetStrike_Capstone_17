# Build and install the Python dependency bundle

This guide covers the CI-built runtime, Python wheelhouse, and offline Linux
packages. For artifact approvals and license/version decisions, see the
[offline tool-bundle inventory](exercise-design/07-offline-tool-bundle-inventory.md).

## Build and verify

Run **Build offline bundle** in GitHub Actions on the branch/revision intended
for testing. Record the workflow run and verify its source revision in
`inventory.json`; use the [release checklist](milestone-release-checklist.md)
for milestone promotion. Download the
`netstrike-offline-bundle-CTRL01-<run-id>` artifact after build,
offline-install verification, and the
[packaged full-play smoke](offline-fullplay-smoke.md) pass.

The workflow targets Linux x86_64/glibc and `CTRL01`, using CPython 3.11.16 and
python-build-standalone release `20260924`. It bundles the shared, module 01,
modules 04–07, dashboard, and Ansible controller/validator requirements;
pinned Galaxy collections; project source trees; and Ubuntu 26.04 amd64
domain-enrollment (`realmd`, `adcli`, SSSD) and DNS/time (`systemd-resolved`,
`chrony`) packages. The Linux baseline installs these packages offline.
Rebuild bundles made before target-baseline-aware dependency updates were
included. Current
pins are in `.github/workflows/offline-bundle.yml` and
`citef-config/requirements.yml`. Local builds use
`scripts/offline_bundle.py` as a normal user with Docker access; the builder
keeps APT's cache inside its disposable amd64 container. APT resolves against an
empty installed-package status file so dependencies already present in the
builder (including systemd, GLib, and Python libraries) are downloaded at the
repository-selected versions rather than omitted. The bundle also includes
`udev`, `systemd-cryptsetup`, `systemd-sysv`, `libnss-systemd`, and
`libpam-systemd` to keep the Ubuntu Server baseline's version-locked systemd
packages consistent.

The builder also resolves the downloaded archives against the checked-in
CTRL01 installed-package baseline, captured from the supplied November 1,
2026 Ubuntu 26.04 amd64 package status. This pulls in companion updates for
installed packages whose exact dependencies would otherwise break when their
libraries are upgraded (for example util-linux, Perl, GLib introspection, and
libc development packages). It repeats target and forward resolution until no
new archives are added. It does not request a full OS upgrade, and package
removal is prohibited during resolution and deployment.

Verification checks both the complete forward dependency set and compatibility
with that target baseline using only local archives, without repository
indexes or networking, then exercises an offline install in the Ubuntu
container. The baseline's solver metadata is included separately in
`destinations/CTRL01/linux-package-baseline.status` and hash-recorded as
`linux_package_baseline` in `inventory.json`. It is not copied into the
target's dpkg database.

For a different image or changed installed-package set, copy
`/var/lib/dpkg/status` from the target to the build machine, then refresh the
baseline before running CI:

```sh
python scripts/offline_bundle.py capture-linux-baseline \
  --status /path/to/ctrl01-dpkg-status.txt \
  --output citef-config/files/ubuntu-26.04-amd64-package-baseline.status
```

This keeps package names, versions, selections, and dependency/conflict fields,
not descriptions, maintainers, or conffile paths. Commit the refreshed
baseline with the intended build revision. A local build can instead pass
`--linux-package-status /path/to/ctrl01-dpkg-status.txt`. Capture each
distinct Linux target baseline before assuming one bundle supports it.

If Linux AD installation reports conflicting exact-version dependencies,
rebuild and transfer a fresh bundle instead of mixing archives from different
builds or downloading individual libraries on the offline VM. Use a bundle
built from repositories at least as current as the target's installed baseline;
this is a baseline-specific dependency update, not support for arbitrary
additional packages. Provisioning clears its staged package directory before
copying the new bundle and installs without downloads or recommended packages.

## Extract and deploy

The GitHub artifact is a ZIP containing the bundle tarball. Transfer it through
the approved route to `ANSIBLE01`, extract, and verify every bundled file:

```sh
unzip netstrike-offline-bundle-CTRL01-RUN_ID.zip
mkdir -p offline-bundle
tar -xzf netstrike-CTRL01-RUN_ID.tar.gz -C offline-bundle
cd offline-bundle/netstrike-offline-bundle
sha256sum -c SHA256SUMS
```

`destinations/CTRL01/` is the payload destination, not the Ansible host. Deploy
from the repository root on `ANSIBLE01` using [`citef-config/README.md`](../citef-config/README.md)
and `provision.sh`. The wrapper verifies the bundle, extracts the runtime,
installs hash-locked Python dependencies and pinned collections offline, then
provisions from its extracted source tree. Pass the application bundle,
licensed-installers archive, environment, private secrets file, deployment
version, and unique run ID in the documented order. Use approved secret
management and a fresh restricted work directory; never put credentials in
Git, command arguments, or logs. `SPLUNK01` is Cyber-Range managed and is not
configured by this project.

Approved deployments also require configured TLS material and secret-managed
controller/readiness credentials. `provision.sh` runs provisioning and its
validation; it does **not** run the separate `readiness.yml` playbook. Verify
readiness, snapshot identity, network isolation, emergency-stop reachability,
Splunk ingestion, and admission independently with range staff.

## Licensed artifact archive layout

The separate `licensed-installers.tar.gz` argument to `provision.sh` is the
licensed product archive, not the CI-built application dependency bundle
described above. Its entries must include this directory structure so extraction under
the application bundle's `source/` directory places files where `environment.json`
and artifact validation expect them:

```text
licensed-installers/
└── CITEF-RELEASE/
    ├── linux/
    │   └── splunkforwarder-10.0.1-c486717c322b-linux-amd64.deb
    ├── sysmon/
    │   └── Sysmon.zip
    └── windows/
        └── splunkforwarder-10.0.1-c486717c322b-windows-x64.msi
```

In particular, archive paths are rooted at `licensed-installers/CITEF-RELEASE/`;
do not add an extra enclosing directory. The Linux and Windows Universal
Forwarder installers and Sysmon ZIP are checked against the approved hashes in
`environment.json`. The Sysmon configuration is maintained separately at
`citef-config/files/sysmon-config.xml`, not inside this archive.

The optional [source checker](offline-release-source-check.md) compares pristine
source trees with a trusted revision and inventory digest. Run it before
provisioning installs collections under `source/citef-config/collections`;
that changes the source tree. It supplements `SHA256SUMS` and install
verification. `requirements.lock` contains pip hashes; `inventory.json` records
the source revision, runtime, packages, and collections, including hashes,
licenses, destinations, and offline install methods. Review unknown metadata
before approving a transfer.

## Smoke-test scope

CI runs the packaged full-play smoke under kernel network isolation with the
bundled interpreter; see [scope and evidence](offline-fullplay-smoke.md). The
optional manual UI check is an identity-only observation, not full-play or range
acceptance. Neither test replaces live Ansible/systemd, Windows/AD, Splunk, or
snapshot checks.

Run the manual check only on a disposable Linux amd64 VM using the project's
accepted isolation method (DNS blocking is sufficient evidence for #79 per
Patrick's October 31 decision). Use a fresh database and run ID, temporary credentials, one Uvicorn
process bound to loopback, and an SSH tunnel for remote viewing. Do not use
production secrets or expose the HTTP listener.

From the bundle root, extract the runtime and install the locked requirements:

```sh
tar -xzf runtime/python-runtime.tar.gz
python/bin/python3.11 -m pip install \
  --no-index --find-links=destinations/CTRL01/wheelhouse \
  --require-hashes -r destinations/CTRL01/requirements.lock
```

In a private VM shell, prepare isolated state and ephemeral test credentials:

```sh
mkdir -p "$HOME/netstrike-smoke" && chmod 700 "$HOME/netstrike-smoke"
export NETSTRIKE_PORTAL_DATABASE="$HOME/netstrike-smoke/portal.sqlite3"
export NETSTRIKE_RUN_ID="offline-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
export NETSTRIKE_IDENTITY_AUDIT_KEY="$(openssl rand -hex 32)"
export NETSTRIKE_SSO_ALLOWED_ORIGINS='["http://127.0.0.1:18080"]'
unset NETSTRIKE_SCENARIO_PATH NETSTRIKE_IMPACT_ROOT NETSTRIKE_PROFILE_FIXTURE
export FACILITATOR_TOKEN="$(openssl rand -hex 32)"
export PARTICIPANT_TOKEN="$(openssl rand -hex 32)"
export NETSTRIKE_PORTAL_TOKENS="$(
python/bin/python3.11 -c '
import json, os
print(json.dumps({
    os.environ["FACILITATOR_TOKEN"]: {"actor_id": "test-facilitator", "role": "facilitator"},
    os.environ["PARTICIPANT_TOKEN"]: {"actor_id": "test-participant", "role": "identity_responder"}
}))
')"
PYTHONPATH="$PWD/source" python/bin/python3.11 -m uvicorn \
  dashboard.app:create_default_app --factory --host 127.0.0.1 --port 18080
```

In another VM shell, check `/health` and the `/participant` and `/facilitator`
pages. Use `ssh -L 18080:127.0.0.1:18080 USER@TEST_VM` to view them remotely.
The facilitator readiness report must identify `local_application_only`;
unauthenticated access returns 401 and participant access returns 403:

```sh
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:18080/api/facilitator/readiness
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $PARTICIPANT_TOKEN" \
  http://127.0.0.1:18080/api/facilitator/readiness
curl -fsS -H "Authorization: Bearer $FACILITATOR_TOKEN" \
  http://127.0.0.1:18080/api/facilitator/readiness
```

Do not call `/api/facilitator/start`. Optionally call
`/api/facilitator/prepare` once with the facilitator token and confirm the
readiness audit persists. Capture only non-secret evidence (VM/image, egress
controls, run/revision, bundle hash, route and authorization results). Never
record tokens, audit keys, Splunk secrets, or synthetic credentials. Stop
Uvicorn, preserve approved evidence, then restore the VM snapshot or remove the
test database. Do not reuse the run ID or database after restart; SQLite does
not restore live runtime state. This UI check does not verify Splunk/HEC, indexes
or retention, DNS/NTP, snapshots, emergency stop, Windows behavior, or
participant admission.

## Deployment boundary

The bundle includes the portable CPython runtime, locked wheels, selected source
trees and dependencies, pinned Ansible collection archives, and `inventory.json`
metadata. It excludes general OS packages, VM images, credentials, and licensed
products such as Splunk, Universal Forwarder, and Sysmon. It includes the
Ubuntu 26.04 domain/DNS/time packages and their required dependency updates,
including version-matched systemd baseline packages, which `linux_baseline`
installs offline.
Targets require Linux x86_64/glibc; these OS packages require Ubuntu 26.04.
Review python-build-standalone terms before redistribution. The temporary
Actions artifact is not a delivery-readiness certificate. The team controls
exercise VM allocation, network configuration, and offline transfer under
delegated Cyber Range authority; no additional configuration approval is
outstanding. Validate the selected bundle/configuration against the deployed
targets and retain its identity with the evidence.

The [provisioning validation report](offline-bundle-provisioning-validation.md)
records the October 15 and October 21 local rehearsals, not range acceptance.
On October 21, restore and readiness were exercised three times but not in
consecutive cycles; the local test used Docker-hosted Splunk and DNS blocking.
Patrick accepts that provisioning and DNS-blocking evidence for #79's tested
configuration. It is not a technical certificate of all-path Internet-egress
blocking or blanket validation of later source revisions. See the
[remaining baseline screenshot checklist](offline-bundle-provisioning-validation.md#baseline-evidence-to-capture).
