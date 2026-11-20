# Deployment guides

Start with the deployment-input contract when inspecting configuration, then
use the runbook for provisioning and post-deployment checks. Dated evidence
documents record scoped results, not blanket exercise acceptance.

| Document | What it covers |
|---|---|
| [Deployment inputs](application-deployment-contract.md) | Read-only configuration inspection before startup side effects |
| [Full-play deployment runbook](full-play-deployment-guide.md) | Provisioning, verification, and next-run handoff |
| [Offline bundle](offline-bundle.md) | Build, verify, install, and smoke-test the Python bundle |
| [Provisioning validation](offline-bundle-provisioning-validation.md) | Dated local validation evidence and its limits |
| [Offline full-play smoke](offline-fullplay-smoke.md) | Packaged runtime/HTTP workflow gate |
| [Offline source check](offline-release-source-check.md) | Selected-source comparison against a recorded digest |
| [Splunk Sysmon ingestion](splunk-sysmon-ingest.md) | Receiver setup and Windows Sysmon forwarding |
| [Application readiness](../application/application-readiness.md) | Local preflight and guarded start |
| [Milestone release checklist](milestone-release-checklist.md) | Source-matched evidence and release gates |
