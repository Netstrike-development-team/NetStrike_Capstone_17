# Maintained application security gate

`Security Analysis` retains the `bandit` job identity and runs on PRs and pushes
to `dev` and `main`. It uses Bandit 1.9.4, read-only repository permissions and
a five-minute job limit. This is an application-quality gate, not a new exercise
feature, a penetration test or Cyber Range acceptance.

## Blocking scope

Two strict scans cover:

- `dashboard`, `orchestrator`, `shared` and `scripts`, excluding `tests` and
  `__pycache__` directories.
- The maintained profile loader (`modules/01-osint-profiler/exercise_profiles.py`)
  and identity, endpoint, cloud and impact action adapters (`identity_actions.py`,
  `endpoint_actions.py`, `cloud_actions.py`, `impact_actions.py` in modules 04–07).

Medium/high findings at any confidence level block the job. Low-severity findings
are outside this blocking threshold; they are not a claim of zero risk. Scan
commands use `set -e`, without `continue-on-error` or ignored exit codes.
`scripts/check_security_report.py` also rejects scan read/parse errors, missing or
malformed/duplicate JSON fields, empty scans and findings in the filtered report.
The helper uses only the standard library and prints fixed status messages,
not raw source or report content. It is CI tooling, not a deployment prerequisite.

The separate legacy-module report is explicitly informational. At the October 5
inspection it included B108 (medium severity, temporary-path handling) in
`modules/07-ransomware-sim/main.py`; that legacy entry point is not the maintained
safe impact adapter. This PR neither accepts nor activates legacy attack scripts.
Do not treat its best-effort report as proof the legacy modules passed.

The upload step runs even after failure and retains available reports in
`bandit-report` for 14 days: legacy text, application JSON and adapter JSON. A
failed earlier step can prevent a later scan from running; missing reports are
not a pass. Preserve relevant artifacts before retention expires. No branch
protection settings change here; reviewers enforce the gate until configured.

## Recorder correction

The maintained-code scan exposed B310 in the walkthrough recorder's default
`urlopen` call. Python API requests now require an explicit `http://127.0.0.1:PORT`
origin and a local path. Credentials in origins, external/file/HTTPS URLs,
invalid ports, fragments, network-path references, control characters, whitespace
and backslashes are rejected before opening a connection.

These requests bypass environment proxies and reject redirects, including
same-origin redirects. Their bearer credentials and JSON bodies cannot be
forwarded by the opener to a redirect destination. Legitimate local GET/POST
methods, query strings, headers and bodies remain supported. This is specifically
the recorder's Python request helper, **not** a network sandbox for Playwright,
browser navigation, all subprocesses or every application HTTP client.

Regression tests use temporary loopback HTTP servers, require no recording
libraries, make no external requests and close their listeners. They exercise
301/302/303/307/308 redirects, GET/POST, proxy environment variables, invalid URLs
and normal requests. Other tests reject invalid security reports and inspect the
workflow's strict-scan/retention contract. No video or visual browser validation
is claimed by these tests; the existing walkthrough narrative is unchanged.

## Local reproduction

With Bandit 1.9.4 installed in a development environment, write reports outside
the checkout. Run each command successfully before the next:

```sh
python -m bandit -r dashboard orchestrator shared scripts \
  -x /tests/,/__pycache__/ -ll -f json -o /tmp/netstrike-application-security.json
python scripts/check_security_report.py /tmp/netstrike-application-security.json
python -m bandit \
  modules/01-osint-profiler/exercise_profiles.py \
  modules/04-mfa-fatigue-sim/identity_actions.py \
  modules/05-lateral-movement/endpoint_actions.py \
  modules/06-cloud-exfil/cloud_actions.py \
  modules/07-ransomware-sim/impact_actions.py \
  -ll -f json -o /tmp/netstrike-adapter-security.json
python scripts/check_security_report.py /tmp/netstrike-adapter-security.json
python -m pytest scripts/tests/test_security_report.py scripts/tests/test_walkthrough_http.py -q
```

This complements the [strict full-play checks](milestone-release-checklist.md).
Rehearsal source fingerprints include the recorder, report guard and security
workflow; matching source still does not prove a tool ran or a deployed VM passed.
Patrick owns offline installation, Windows/Sysmon/Splunk and environment proof;
Anna owns content and real learner checks; Ashley owns client acceptance.
