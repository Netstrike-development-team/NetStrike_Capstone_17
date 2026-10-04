# Operation Silent Spider — Blue-Team Exercise Design Package

**Status:** Scope accepted by the Cyber Range on September 24, 2026, with the duration and reset changes recorded below

**Target:** Zero-cost, blue-team-only MVP completed in 12 weeks

**Exercise format:** One operations-based incident-response exercise

**Expected delivery:** CITEF-ready scenario, supporting software, documentation, and reset procedure

## Decision

The three-month project is feasible only with the following scope boundary:

- Deliver one polished blue-team scenario, not a general-purpose cyber-range platform.
- Support one agreed CITEF topology and one team per isolated exercise instance.
- Use Splunk supplied by the Cyber Range; do not build a competing SIEM.
- Keep cloud activity inside a clearly identified Python mock service.
- Use deterministic, checkpoint-based branches rather than an open-ended adaptive attacker.
- Use Ansible for provisioning, seeding, configuration, and readiness checks;
  restore clean VM snapshots between deliveries.
- Defer MITRE CALDERA; use only registered MSEL actions in the blue-team MVP.
- Use marker files and simulated service impact; never encrypt real VM disks or exercise infrastructure.
- Defer manual red-team play, GHOSTS, multi-tenant support, public-cloud deployment, and a custom detection dashboard.

The exercise begins after an identity compromise has occurred. Participants investigate the initial evidence, contain the account, and respond while controlled attacker actions continue through Active Directory discovery, mock cloud data access, and safe simulated impact.

## Package contents

| Document | Purpose |
|---|---|
| [01-exercise-charter.md](01-exercise-charter.md) | Audience, prerequisites, team, duration, objectives, roles, and permitted actions |
| [02-storyline-and-msel.md](02-storyline-and-msel.md) | Complete story, initial state, branches, and Master Scenario Events List |
| [03-telemetry-evidence-matrix.md](03-telemetry-evidence-matrix.md) | Required log sources, expected evidence, learner conclusions, and validation |
| [04-safety-and-reset.md](04-safety-and-reset.md) | Safety controls, emergency stop, reset sequence, and readiness checks |
| [05-guide-outlines.md](05-guide-outlines.md) | Participant, facilitator, evaluator, and solution-guide structures |
| [06-citef-requirements-and-approval.md](06-citef-requirements-and-approval.md) | Meeting-ready CITEF questionnaire, zero-cost fallbacks, decision log, and approval record |
| [07-tools-and-offline-deployment.md](07-tools-and-offline-deployment.md) | Proposed tool stack, licensing responsibilities, EDR decision, and air-gapped installation plan |

## Twelve-week delivery plan

| Weeks | Outcome | Exit criterion |
|---|---|---|
| 1–2 | Approve this package and obtain CITEF/Splunk constraints | Story, topology, objectives, and evidence matrix accepted |
| 3–4 | Complete identity vertical slice | Inject → telemetry → Splunk investigation → containment → verification → reset works |
| 5–6 | Add endpoint/AD stage | Deterministic discovery and containment path works and produces expected telemetry |
| 7–8 | Add mock cloud and safe impact stages | Cloud containment, impact branch, and recovery work without destructive behavior |
| 9 | Participant/facilitator workflow and scoring | All injects, submissions, checkpoints, hints, and event records work |
| 10 | Documentation, installer, health check, and reset automation | A new operator can deploy and reset from the guides |
| 11 | CITEF deployment and two full dry runs | Complete scenario runs twice from clean snapshots |
| 12 | Defect correction, final dry run, demo recording, and release | Acceptance checklist passes and fallback recording exists |

Weeks 11–12 are deliberately protected. Features that threaten that buffer are deferred.

## MVP definition of done

The project is exercise-ready when:

1. A facilitator can initialize, start, pause, advance, and stop the exercise without editing source code.
2. Participants can complete all five learning objectives using Splunk and approved administration interfaces.
3. Every planned attacker action and important defender action is tagged with a unique `run_id` and timestamp.
4. Each checkpoint selects one of the documented branch outcomes from verified environment state.
5. Expected telemetry reaches Splunk and is discoverable using the solution-guide searches.
6. No stage requires real credentials, real personal data, Internet access, paid cloud resources, or destructive encryption.
7. A failed module produces a visible controller error and can be skipped or retried safely.
8. The complete environment can be restored from clean snapshots and passes the automated readiness check before participants enter.
9. The exercise has passed at least three complete dry runs, including one on CITEF.
10. Participant, facilitator, evaluator, solution, safety, deployment, and reset documentation is complete.

## Research basis

This package follows the objective-led, operations-based exercise approach in the [ENISA Cybersecurity Exercise Methodology](https://www.enisa.europa.eu/sites/default/files/2026-02/The%20ENISA%20Cybersecurity%20Exercise%20Methodology.pdf), the evaluation and improvement lifecycle in [FEMA HSEEP](https://preptoolkit.fema.gov/web/hseep-resources), and the participant/facilitator/AAR structure in [NIST SP 800-84](https://nvlpubs.nist.gov/nistpubs/legacy/sp/nistspecialpublication800-84.pdf). Learner tasks are aligned broadly with the [NICE Framework](https://www.nist.gov/itl/applied-cybersecurity/nice/nice-framework-resource-center/getting-started). Threat behavior is derived from the [2025 joint Scattered Spider advisory](https://www.cisa.gov/sites/default/files/2025-07/aa23-320a-scattered-spider_1.pdf) and the [MITRE ATT&CK Scattered Spider entry](https://attack.mitre.org/groups/G1015/).

## Approval gates

The Cyber Range has accepted the audience, objectives, safety rules, blue-team
scope, VM flexibility, Splunk availability, and snapshot restoration approach.
Remaining confirmations include the VM mapping, Splunk configuration and
permissions, the complete offline bundle and license terms, and delivery dates.

Use [06-citef-requirements-and-approval.md](06-citef-requirements-and-approval.md)
to collect these decisions, record exceptions, re-estimate the backlog, and
capture named approval.
