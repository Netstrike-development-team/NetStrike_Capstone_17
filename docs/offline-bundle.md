# Build and install the Python dependency bundle

This guide covers the CI-built Python runtime and wheelhouse used to bootstrap
an air-gapped CITEF controller/portal environment. It is a build/install
procedure, not the complete decision register: the current tool stack, approval
status, artifact inventory, unresolved license/version checks, and test record
live in [exercise-design/07-offline-tool-bundle-inventory.md](exercise-design/07-offline-tool-bundle-inventory.md).

## 1. Build it in GitHub Actions

1. Open the repository's **Actions** tab.
2. Select **Build offline bundle**, then **Run workflow**.
3. Wait for the bundle build and offline-install verification to pass.
4. Download the `netstrike-offline-bundle-CTRL01-<run-id>` artifact.

The workflow currently pins Linux x86_64/glibc, `CTRL01`, CPython `3.11.16`,
and python-build-standalone release `20260924`. The wheelhouse covers shared,
module 01 and modules 04–07, dashboard, and Ansible-controller/validator
requirements. The bundle also contains the `modules/`, `dashboard/`,
`citef-config/`, `shared/`, `orchestrator/`, and `schemas/` source trees plus
pinned Ansible Galaxy collections and manifest metadata. These pins and inputs are
in `.github/workflows/offline-bundle.yml` and `citef-config/requirements.yml`.

## 2. Verify and install

The GitHub artifact is released as a ZIP containing the bundle archive. Extract
it into the approved staging area:

```sh
unzip netstrike-offline-bundle-CTRL01-RUN_ID.zip
mkdir offline-bundle
tar -xzf netstrike-CTRL01-RUN_ID.tar.gz -C offline-bundle
cd offline-bundle/netstrike-offline-bundle
sha256sum -c SHA256SUMS
tar -xzf runtime/python-runtime.tar.gz
python/bin/python3.11 -m pip install \
  --no-index \
  --find-links=destinations/CTRL01/wheelhouse \
  --require-hashes \
  -r destinations/CTRL01/requirements.lock
python/bin/ansible-galaxy collection install \
  --offline \
  --collections-path source/citef-config/collections \
  ansible/collections/*.tar.gz
```

This installs the locked dependencies and collections without needing Python
preinstalled or Internet access to a package index. The project source is under
`source/`. `SHA256SUMS` covers every bundled file; the lock file includes wheel
hashes for pip's `--require-hashes` check, and `inventory.json` records the
source trees, Python packages, and collection versions/licenses. Every
inventory entry also includes its SHA-256, destination VM, and offline install
method; review explicit UNKNOWN metadata before approving a transfer.

## 3. Run the application smoke test on an isolated Linux VM

This smoke test starts the bundled portal with test-only credentials, a fresh
SQLite database, and a unique run ID. It checks application startup and local
HTTP/UI behavior only; it does not configure Splunk or establish full range
readiness. Perform it on a disposable Linux amd64 VM with Internet egress
blocked. Bind the service to loopback; access it remotely only through SSH
port-forwarding. Keep the VM's approved management connection available.

1. Transfer the workflow artifact through the approved route. On the VM, extract
   and verify it using the steps above. Use the extracted
   `netstrike-offline-bundle` directory as the working directory below.
2. Install the hash-locked requirements from the bundled wheelhouse:

   ```sh
   tar -xzf runtime/python-runtime.tar.gz
   python/bin/python3.11 -m pip install \
     --no-index \
     --find-links=destinations/CTRL01/wheelhouse \
     --require-hashes \
     -r destinations/CTRL01/requirements.lock
   ```

3. In a private shell on the VM, configure an isolated database, unique run,
   and ephemeral facilitator/participant credentials. `openssl rand` creates
   the test secrets; do not record their values or commit them:

   ```sh
   mkdir -p "$HOME/netstrike-smoke"
   chmod 700 "$HOME/netstrike-smoke"
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
       os.environ["FACILITATOR_TOKEN"]: {
           "actor_id": "test-facilitator", "role": "facilitator"
       },
       os.environ["PARTICIPANT_TOKEN"]: {
           "actor_id": "test-participant", "role": "identity_responder"
       }
   }))
   '
   )"
   ```

4. Start one Uvicorn process, bound to loopback, with the bundled source tree
   on Python's import path:

   ```sh
   PYTHONPATH="$PWD/source" python/bin/python3.11 -m uvicorn \
     dashboard.app:create_default_app \
     --factory \
     --host 127.0.0.1 \
     --port 18080
   ```

   Leave it running. From your workstation, create an SSH tunnel:

   ```sh
   ssh -L 18080:127.0.0.1:18080 USER@TEST_VM
   ```

   Open `http://127.0.0.1:18080/participant` and
   `http://127.0.0.1:18080/facilitator` locally. Do not expose this HTTP test
   listener to other hosts or use production credentials.

5. In a second VM shell, check service liveness and UI routes:

   ```sh
   curl --fail --silent --show-error http://127.0.0.1:18080/health
   curl --fail --silent --show-error -o /dev/null \
     -w 'participant page: HTTP %{http_code}\n' \
     http://127.0.0.1:18080/participant
   curl --fail --silent --show-error -o /dev/null \
     -w 'facilitator page: HTTP %{http_code}\n' \
     http://127.0.0.1:18080/facilitator
   ```

6. Test local readiness and role separation. The report must identify itself as
   `local_application_only`; unauthenticated readiness must be denied, and a
   participant must not access facilitator readiness:

   ```sh
   curl --fail --silent --show-error \
     -H "Authorization: Bearer $FACILITATOR_TOKEN" \
     http://127.0.0.1:18080/api/facilitator/readiness

   curl --silent --output /dev/null --write-out 'unauthenticated readiness: HTTP %{http_code}\n' \
     http://127.0.0.1:18080/api/facilitator/readiness
   curl --silent --output /dev/null --write-out 'participant readiness: HTTP %{http_code}\n' \
     -H "Authorization: Bearer $PARTICIPANT_TOKEN" \
     http://127.0.0.1:18080/api/facilitator/readiness
   ```

   Expected denial codes are 401 and 403, respectively. Do not call
   `/api/facilitator/start`; starting play is unnecessary for this smoke test.
   Optionally test an audited write on this disposable instance by preparing
   once:

   ```sh
   curl --fail --silent --show-error \
     -X POST \
     -H "Authorization: Bearer $FACILITATOR_TOKEN" \
     http://127.0.0.1:18080/api/facilitator/prepare
   ```

   If preparation is tested, inspect the facilitator state/export and confirm
   the readiness audit is persisted. Preparation is not a Splunk or VM
   readiness result.
7. Capture non-secret evidence: date/operator, Linux image/version/architecture,
   Internet-egress denial method/result, workflow run and repository revision,
   bundle SHA-256, dependency-install result, route status codes, readiness
   scope, participant/facilitator authorization results, and any preparation
   audit result. Never include tokens, audit key, HEC/Splunk secrets, or
   synthetic credentials in logs or evidence.
8. Stop Uvicorn with `Ctrl+C`, then restore the VM snapshot or remove the
   dedicated smoke-test database after preserving approved evidence. Do not
   reuse this run ID or SQLite database after a process restart; the application
   does not replay live runtime state from SQLite.

Record this separately from Linux Universal Forwarder/Splunk checks and from
Windows/Sysmon acceptance. A successful smoke test does not verify HEC delivery,
the `netstrike` index/RBAC/retention, DNS/NTP, snapshots, emergency stop, or
Windows-specific behavior.

## CITEF deployment boundary

The bundle contains a portable CPython runtime, wheels for the selected Python
requirements, the module/dashboard/Ansible configuration source trees and their
`shared`, `orchestrator`, and `schemas` dependencies, pinned Ansible collection
archives, and package metadata in `inventory.json`. The inventory records the
repository commit, runtime version/source, and each package, source tree, and
collection's name, version, license, owner, SHA-256, destination VM, offline
installation method, and file path. `requirements.lock` carries pip's wheel
hashes; `SHA256SUMS` is the integrity manifest for all bundle files.

It does not include OS packages, VM images, credentials, or licensed products
such as Splunk, Universal Forwarder, or Sysmon. The target must be compatible
with Linux x86_64 and glibc. Review the `python-build-standalone` distribution
terms before redistributing the bundle. The Actions artifact is temporary CI
storage, not CITEF approval or an approved transfer channel. Test installation
and exercise readiness on a clean, network-isolated target VM before delivery.

For tool decisions, unresolved approvals, package inventories, and the clean-VM
verification record, see [exercise-design/07-offline-tool-bundle-inventory.md](exercise-design/07-offline-tool-bundle-inventory.md).
