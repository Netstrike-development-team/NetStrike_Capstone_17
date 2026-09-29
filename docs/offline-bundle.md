# Build and install the Python bundle

## 1. Build it in GitHub Actions

1. Open the repository's **Actions** tab.
2. Select **Build offline bundle**, then **Run workflow**.
3. Wait for the build and offline-install verification to pass.
4. Download the `netstrike-offline-bundle-CTRL01-<run-id>` artifact from the
   completed run.

The workflow currently pins Linux x86_64/glibc, `CTRL01`, CPython `3.11.16`,
and python-build-standalone release `20260924`. It bundles the Python runtime
dependencies declared by the shared requirements and modules 04–07. These
pins are in `.github/workflows/offline-bundle.yml`.

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
```

This installs the locked dependencies without needing Python preinstalled or
accessing a package index. `SHA256SUMS` covers every bundled file; the lock
file includes wheel hashes for pip's `--require-hashes` check.

## What's included and what's not

The bundle contains only a portable CPython runtime, wheels for the selected
Python requirements, and package metadata in `inventory.json`. Project source
and configuration are not included; get those from the matching repository
revision recorded in `inventory.json`. That inventory records the commit,
runtime version/source, and each package's name, version, license, owner, and
file path. `requirements.lock` carries pip's wheel hashes; `SHA256SUMS` is the
integrity manifest for all bundle files.

It does **not** include Windows support, Ansible, OS packages, VM images,
credentials, or licensed products such as Splunk, Universal Forwarder, and
Sysmon. The target must be compatible with Linux x86_64 and glibc. Review the
`python-build-standalone` distribution terms before redistributing the bundle.
The Actions artifact is temporary CI storage, not CITEF approval or the
approved transfer channel. Test installation and exercise readiness on a
clean, network-isolated target VM before delivery.

For proposed artifacts, unresolved approvals, and the clean-VM test record,
see the [offline tool bundle inventory](exercise-design/07-offline-tool-bundle-inventory.md).
