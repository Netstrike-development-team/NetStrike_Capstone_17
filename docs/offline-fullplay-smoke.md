# Actual offline-bundle application smoke (#185)

This developer gate closes the gap between **a bundle that installs** and **an
application that starts and operates from that installed bundle**. It uses no
paid resource or CITEF VM. Aya owns this gate; Patrick still owns actual range
installation, Windows/AD/UF/Splunk acceptance and VM snapshot recovery.

## What runs

The existing `Build offline bundle` workflow now runs on pull requests and pushes
to `dev`/`main`, as well as manual dispatch. It builds the actual committed source
and pinned Linux amd64 portable CPython/wheels/Ansible collections, keeps the
existing checksum/install checks, then runs an additional strict smoke step.

The launcher creates a new network namespace with only loopback, enables `lo`,
then drops to the runner user with all capabilities removed and no-new-privileges
set. The driver observes these kernel properties and compares the actual current
namespace with the host namespace reference recorded by the trusted launcher.
The application and its installers never run as root. No network fallback is
offered when isolation is unavailable; this is deliberately Linux amd64 only.
This is network isolation of trusted reviewed project code, not a complete
malware/container/filesystem sandbox or administrator-proof attestation.

`scripts/offline_smoke.py` verifies the independently supplied whole-archive SHA,
bounded archive members/expanded sizes, exact file checksums, inventory hashes,
all required source trees and expected committed revision. It extracts a **fresh
bundled runtime**, installs only bundled hash-locked wheels (`--no-index`,
`--require-hashes`, isolated pip configuration, no cache), and installs the local
collections with `ansible-galaxy --offline`. All this happens after isolation.

The app worker is `dashboard/offline_smoke.py`, included in the existing source
inventory. The driver invokes it with the extracted interpreter's `-I -B`, a
clean environment, the extracted source path and a non-checkout working directory.
The worker rejects a non-packaged interpreter, imports outside packaged source/
runtime, changed source inventory and invalid full-play configuration. Host
`PYTHONPATH`, user site packages, checkout imports, proxy settings, real portal
credentials and cached pip dependencies are not fallback sources. Native OS
libraries remain part of the Linux runner; this is not a whole-OS VM image.

## Representative journey

The production app factory boots a real Uvicorn HTTP listener on `127.0.0.1` with
an ephemeral port. The worker checks actual routes, not mocked API responses:

- Health/static pages and assets, authentication/role denial and stale-run guard.
- Read-only full-play preflight, prepare/start, pause/resume and accelerated play.
- Available identity/helpdesk evidence, DP1 and a six-entry timeline submission.
- A preview and execution of a safe simulated session revocation; an unapproved
  target is denied. The remaining response controls are deliberately omitted.
- Missed-response cloud/impact branches, disposable decoy availability, recovery
  preview, restore and health validation. No real identity/cloud/host is changed.
- Stop, provisional review and canonical export, application reset to a new ID,
  fresh start/stop and immutability of the archived prior review.
- Canonical and separate learner publication, exact projection reconciliation,
  both run IDs and a duplicate-free local retry.
- The packaged learner/export comparison utility for both run IDs, with explicitly
  synthetic local receiver fixtures and injected loss/duplication/change/wrong-run
  faults. Its receipt is not a real Splunk export or live ingestion proof.

This is a representative packaged smoke, **not all 16 branching combinations**.
The separate full-play rehearsal retains its 24-case branch/fault coverage and
strict source fingerprints. Developer synthetic submissions are not human grades
or usability evidence. The worker does not run a real browser or wait 2h50.

## Reproduce

Preview is inert, including on macOS:

```sh
python scripts/offline_smoke.py
```

For execution, use a reviewed Linux amd64 checkout, an actual built/downloaded
bundle, its recorded revision/SHA256 and a **new** private output directory whose
parent exists. Prepare Linux tools/Python before disabling networking. The exact
`unshare` / `setpriv` launcher is versioned in `.github/workflows/offline-bundle.yml`;
use that recipe rather than removing the driver guards to make a local run pass.

Inside that correctly prepared namespace, after privilege drop:

```sh
python -I -B scripts/offline_smoke.py \
  --archive /approved/netstrike-CTRL01-RELEASE.tar.gz \
  --output /approved/new-smoke-output \
  --expect-revision RECORDED_40_HEX_REVISION \
  --expect-archive-sha256 RECORDED_64_HEX_ARCHIVE_SHA256 \
  --host-network-namespace 'net:[RECORDED_HOST_NAMESPACE_NUMBER]' \
  --execute
```

The namespace reference is an observation from the trusted host-side launcher,
not an arbitrary claim that a computer is offline. Checksums bind selected bytes
and detect mutation; they do not prove code review, source authenticity or client
approval. Review the workflow/release before executing a bundle's runtime/code.

## Evidence, failure and handoff

The output directory is new and private. It retains summary, observed network
boundary, source check, preflight, HTTP status checks, synthetic review, the
initial-run HTTP event export, the final both-run canonical/learner exports, the
explicitly synthetic comparison receipt and
bounded install/application logs. The final canonical/learner pair supports
independent exact projection reconciliation after artifact download. Commands time out, excessive
output is refused before it exceeds the log cap, and failed child process groups
are killed. Existing outputs are never overwritten or automatically repaired.
Partial diagnostics remain for inspection; do not reuse a failed output path.

CI uploads only an explicit diagnostic allowlist, not the working SQLite database,
credentials, runtime, entire extracted source, fixture working tree or user data.
Failure fails the job; the diagnostic upload does not convert a failure to success.
The actual built archive is uploaded only after successful prior verification.

`passed=true` means this reviewed bundle ran the synthetic packaged journey with
the recorded local isolation boundary. `external_readiness_verified`,
`splunk_ingestion_verified` and `full_exercise_acceptance` stay false. Still needed:
Patrick's actual Ansible/systemd installation and host binding, Windows/AD and
Sysmon, Splunk field/time/role/volume reconciliation, VM/UF snapshot behavior,
Anna's content/usability rehearsal and final CITEF acceptance.

Implementation references: [network namespaces](https://man7.org/linux/man-pages/man7/network_namespaces.7.html),
[unshare](https://man7.org/linux/man-pages/man1/unshare.1.html),
[setpriv](https://man7.org/linux/man-pages/man1/setpriv.1.html).
