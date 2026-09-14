# Exercise Charter

## Identity

| Field | Definition |
|---|---|
| Name | Operation Silent Spider |
| Organization | SimCorp, a wholly fictitious company |
| Format | Facilitated, operations-based blue-team exercise |
| Threat | Fictitious actor behavior modelled on publicly reported Scattered Spider/UNC3944 tradecraft |
| Primary purpose | Practise investigation, containment, recovery, and incident communication |
| MVP duration | 3 hours 40 minutes: 20-minute briefing, 2 hours 50 minutes of play, 30-minute hotwash |
| Delivery model | One team in one isolated CITEF instance |
| Cost assumption | No paid service or public-cloud consumption required |

## Audience

The MVP is designed for post-secondary cybersecurity learners, co-op students, and junior security practitioners preparing for SOC or incident-response work. It is not designed as an expert threat-hunting assessment or an introductory computer-literacy lab.

### Prerequisite capability

Participants should be able to:

- explain IP addresses, DNS, HTTP, authentication, sessions, passwords, and MFA;
- recognize the purpose of Active Directory, user accounts, security groups, and endpoints;
- run basic command-line commands and navigate a Windows or Linux host;
- perform introductory Splunk searches, filter by time and fields, and inspect an event;
- describe the basic stages of incident response; and
- distinguish evidence from an unverified assumption.

Exploit development, malware analysis, advanced SPL, AWS experience, and prior red-team experience are not prerequisites. If participants have never used Splunk, they should complete a separate 60–90 minute orientation before exercise day.

## Team size and staffing

- **Ideal participant team:** 4 people
- **Supported participant range:** 2–6 people
- **Minimum exercise staff:** 1 facilitator/controller and 1 evaluator/technical observer
- **Preferred exercise staff:** 1 lead facilitator, 1 evaluator, and 1 technical operator

With two participants, roles are combined into incident lead/analyst and infrastructure responder. With six participants, identity and cloud administration may be separate roles.

## Learning objectives

The objectives are measured against scenario time, recorded evidence, and verified lab state.

### LO1 — Triage the identity incident

Within 25 minutes of the first inject, classify the event as a likely account compromise, identify the primary compromised identity, and submit at least three relevant artifacts from at least two data sources.

**Successful evidence:** correct identity, defensible classification, and three artifact references with timestamps or event identifiers.

### LO2 — Reconstruct the intrusion

Before the first containment checkpoint, construct a timeline containing at least six significant events in the correct order across identity, helpdesk/web, and endpoint or controller telemetry. Mark each statement as observed fact or analyst inference.

**Successful evidence:** at least five of six events are correct, ordering is materially correct, and facts are not presented as unsupported certainty.

### LO3 — Contain identity and endpoint access

Before the endpoint checkpoint, revoke the malicious session, reset the compromised credential, remove the unauthorized MFA factor, and isolate the affected endpoint or otherwise block its simulated remote access path. Preserve the named evidence before destructive remediation.

**Successful state:** all four containment checks pass and no more than one unrelated account or host is disrupted.

### LO4 — Determine and contain cloud data exposure

Before the cloud checkpoint, identify the abused mock-cloud principal, affected bucket, and scope of accessed synthetic records; revoke the unauthorized key or principal and restore the approved bucket policy.

**Successful state:** principal and bucket are correct, exposure estimate matches the allowed tolerance, and both access-key and bucket-policy checks pass.

### LO5 — Recover and communicate

By exercise end, restore the affected simulated service or data set from the known-good exercise backup and submit a concise incident brief covering confirmed scope, business impact, actions taken, remaining risk, and two prioritized follow-up recommendations.

**Successful evidence:** recovery health check passes and the report contains all five required sections without overstating unverified conclusions.

## Participant roles

### Incident lead and scribe

- Assigns investigation and response work.
- Maintains the team timeline and decision log.
- Approves disruptive containment steps.
- Delivers status updates and the final incident brief.

### SOC and forensic analyst

- Searches Splunk and correlates evidence.
- Establishes scope, affected identities, hosts, and time range.
- Preserves requested evidence and proposes containment.

### Identity and helpdesk responder

- Reviews simulated identity and helpdesk administration records.
- Resets exercise credentials, revokes sessions, and removes unauthorized factors.
- Reviews the helpdesk action against the fictitious verification policy.

### Endpoint and Active Directory responder

- Investigates the affected workstation and directory activity.
- Isolates designated hosts and reverses unauthorized lab changes.
- Validates that attacker access has stopped.

### Cloud and recovery responder

- Investigates the Python mock cloud service and its audit logs.
- Revokes mock keys and restores approved permissions.
- Performs the documented recovery validation.

## Exercise-control roles

- **Lead facilitator/controller:** controls pace, delivers injects, accepts participant requests, and selects documented branch actions.
- **Evaluator:** observes without coaching, records evidence against each objective, and assigns rubric ratings.
- **Technical operator:** monitors service health, executes approved retries/resets, and distinguishes exercise effects from platform faults.
- **Simulated people:** facilitator role-plays the employee, manager, helpdesk supervisor, or executive when an inject requires human interaction.

## Permitted participant actions

Participants may:

- search and export exercise-tagged events from Splunk;
- examine designated hosts, files, processes, tickets, and mock-service records;
- collect copies or hashes of artifacts into the approved evidence directory;
- disable or reset designated SimCorp exercise accounts;
- revoke simulated sessions and MFA factors;
- isolate designated lab hosts using the supplied control;
- stop designated simulated attacker or persistence processes;
- revoke mock-cloud keys and correct mock bucket policies;
- restore designated disposable data from the supplied exercise backup;
- use the participant portal to submit evidence, request hints, and communicate decisions; and
- ask the facilitator to simulate actions that are valid but unavailable through the prototype.

Participants may not:

- scan, connect to, or attack any system outside the assigned exercise subnet;
- use real identities, passwords, phone numbers, or personal data;
- contact real employees or conduct real phishing/vishing;
- change Splunk, controller, evaluator, scoring, or hypervisor configuration;
- delete or alter source logs;
- install unapproved offensive software;
- disable exercise safety controls or network isolation;
- perform real encryption, erase disks, destroy snapshots, or target VM images; or
- continue after an emergency-stop instruction.

## Assessment scale

| Rating | Meaning |
|---|---|
| Performed | Objective completed independently and evidence supports the result |
| Performed with support | Objective completed after a hint, facilitator clarification, or minor correction |
| Partially performed | Some required actions or evidence were correct, but the objective state was not achieved |
| Not performed | Required result was absent or materially incorrect |
| Not observed | Platform failure or exercise control prevented fair observation |

The overall suggested weighting is: investigation evidence 40%, containment and recovery state 35%, decision rationale and communication 15%, and timeliness 10%. A public leaderboard is out of scope for the blue-team MVP.
