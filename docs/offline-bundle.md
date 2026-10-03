# Build and install the Python bundle

## 1. Build it in GitHub Actions

1. Open the repository's **Actions** tab.
2. Select **Build offline bundle**, then **Run workflow**.
3. Wait for the build and offline-install verification to pass.
4. Download the `netstrike-offline-bundle-CTRL01-<run-id>` artifact from the
   completed run.

The workflow currently pins Linux x86_64/glibc, `CTRL01`, CPython `3.11.16`,
and python-build-standalone release `20260924`. The wheelhouse covers shared,
module 01 and modules 04–07, dashboard, and Ansible-controller/validator
requirements. The bundle also contains the `modules/`, `dashboard/`,
`citef-config/`, `shared/`, `orchestrator/`, and `schemas/` source trees plus
the pinned Ansible Galaxy collections and their manifest metadata. These pins
and inputs are in `.github/workflows/offline-bundle.yml` and
`citef-config/requirements.yml`.

## 2. Verify and install on the target

The GitHub UI downloads the Actions artifact as a `.zip`. Extract it, then copy
the contained `.tar.gz` bundle to a compatible Linux x86_64 machine. Replace
`RUN_ID` below with the run ID shown in the artifact name:

```sh
unzip netstrike-offline-bundle-CTRL01-RUN_ID.zip
mkdir offline-bundle
tar -xzf netstrike-offline-bundle-CTRL01-RUN_ID.tar.gz -C offline-bundle
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
preinstalled or accessing a package index. The project source is under
`source/`. `SHA256SUMS` covers every bundled file; the lock file includes
wheel hashes for pip's `--require-hashes` check, and `inventory.json` records
the source trees, Python packages, and collection versions/licenses.

## What's included and what's not

The bundle contains a portable CPython runtime, wheels for the selected Python
requirements, the module/dashboard/Ansible configuration source trees and
their `shared`, `orchestrator`, and `schemas` dependencies, pinned Ansible
collection archives, and package metadata in `inventory.json`. The
inventory records the repository commit, runtime version/source, and each
package and collection's name, version, license, owner, and file path.
`requirements.lock` carries pip's wheel hashes; `SHA256SUMS` is the integrity
manifest for all bundle files.

It does **not** include OS packages, VM images, credentials, or licensed
products such as Splunk, Universal Forwarder, and Sysmon. The target must be
compatible with Linux x86_64 and glibc. Review the
`python-build-standalone` distribution terms before redistributing the bundle.
The Actions artifact is temporary CI storage, not CITEF approval or the
approved transfer channel. Test installation and exercise readiness on a
clean, network-isolated target VM before delivery.

For proposed artifacts, unresolved approvals, and the clean-VM test record,
see the [offline tool bundle inventory](exercise-design/07-offline-tool-bundle-inventory.md).
