# Build and install the Python dependency bundle

This guide covers the CI-built application runtime and offline dependencies.
The bundle is separate from the licensed-products archive used by
[`provision.sh`](../../citef-config/README.md). For artifact selection and
licensing decisions, see the [offline tool-bundle inventory](../exercise-design/07-offline-tool-bundle-inventory.md).

## Build and verify

Run **Build offline bundle** in GitHub Actions on the revision intended for
testing. Download the artifact after its build, offline-install checks, and
[packaged full-play smoke](offline-fullplay-smoke.md) pass. Verify the source
revision in `inventory.json` and the archive contents with `SHA256SUMS`.

The bundle targets Linux x86_64/glibc and Ubuntu 26.04 amd64 on `CTRL01`. It
contains CPython 3.11, locked Python wheels, pinned Ansible collections, project
source trees, inventory metadata, and the Linux domain-enrollment and DNS/time
packages needed by the baseline. It is not a VM image or a general OS upgrade.

The Linux package set is tied to the checked-in installed-package baseline. If
the target image or installed packages change, capture its
`/var/lib/dpkg/status` and refresh the baseline before building:

```sh
python scripts/offline_bundle.py capture-linux-baseline \
  --status /path/to/ctrl01-dpkg-status.txt \
  --output citef-config/files/ubuntu-26.04-amd64-package-baseline.status
```

For source revision and inventory checks, see the optional
[offline release source checker](offline-release-source-check.md).

## Transfer and provision

The GitHub artifact is a ZIP containing the bundle tarball. Transfer it to
`ANSIBLE01` through the approved route, extract it, and verify its files:

```sh
unzip netstrike-offline-bundle-CTRL01-RUN_ID.zip
mkdir -p offline-bundle
tar -xzf netstrike-CTRL01-RUN_ID.tar.gz -C offline-bundle
cd offline-bundle/netstrike-offline-bundle
sha256sum -c SHA256SUMS
```

`destinations/CTRL01/` is the payload destination, not the Ansible host. Run
[`provision.sh`](../../citef-config/README.md) from the repository root on
`ANSIBLE01`; that guide documents the required arguments, environment manifest,
and private secrets file. The wrapper installs the bundled runtime and
dependencies offline, then runs provisioning and its validation. It does not
run the separate readiness playbook. Follow the [portal deployment
contract](application-deployment-contract.md) for portal configuration,
credentials, and TLS requirements.

## Licensed installer archive

The separate `licensed-installers.tar.gz` argument is extracted under the
bundle's `source/` directory. Its archive paths must use this layout, without
an additional enclosing directory:

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

The Linux and Windows Universal Forwarder installers and Sysmon ZIP are checked
against the approved hashes in `environment.json`. The Sysmon configuration is
maintained separately at `citef-config/files/sysmon-config.xml`.

## Scope

The bundle excludes VM images, credentials, general OS packages, and licensed
products such as Splunk, Universal Forwarder, and Sysmon. Review the
python-build-standalone terms before redistribution. Successful checksum,
installation, or smoke checks do not establish live range readiness or exercise
acceptance; validate the deployed environment and complete readiness and
admission checks separately. See the [provisioning validation
report](offline-bundle-provisioning-validation.md) for local rehearsal evidence.
