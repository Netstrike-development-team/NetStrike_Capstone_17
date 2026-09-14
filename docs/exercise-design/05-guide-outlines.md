# Exercise Guide Outlines

The following outlines define the documentation set that must be completed before the exercise is released. Information marked facilitator-only or evaluator-only must not appear in participant material.

## Participant guide

1. **Welcome and purpose**
   - Operation Silent Spider overview
   - Learning purpose and non-punitive exercise statement
   - What is simulated versus real
2. **Exercise scope**
   - Start/end times and breaks
   - Assigned team and roles
   - In-scope logical assets and network diagram
3. **Rules of engagement**
   - Permitted and prohibited actions
   - Evidence-storage location
   - Emergency-stop instruction
4. **SimCorp background**
   - Business context
   - Key fictitious people and services
   - Short identity, helpdesk, data-handling, and incident-escalation policies
5. **Access instructions**
   - Jump host or workstation
   - Splunk
   - Participant portal
   - Identity, endpoint/AD, and mock-cloud administration interfaces
6. **How to work the exercise**
   - Receive and acknowledge injects
   - Submit evidence and decisions
   - Request a hint or simulated action
   - Record facts, inferences, and unknowns
7. **Required outputs**
   - Initial classification
   - Incident timeline
   - Containment record
   - Cloud exposure assessment
   - Final incident brief
8. **Reference material**
   - Basic SPL examples that do not reveal scenario answers
   - Time-zone convention
   - Contact and support channel

The participant guide excludes the ground truth, malicious identifiers beyond what appears naturally in play, expected searches, checkpoint times, branch logic, verifier conditions, and scoring answer key.

## Facilitator/controller guide

1. **Exercise intent and learning objectives**
2. **Facilitator responsibilities and boundaries**
3. **Required staffing and contact tree**
4. **Pre-exercise checklist**
   - Baseline readiness record
   - Participant access
   - Splunk data health
   - Portal and communications check
   - Emergency stop
5. **Briefing script**
6. **Complete MSEL**
   - Delivery text and attachments
   - Trigger/timing
   - Expected participant response
   - Branch action
   - Fallback evidence bundle
7. **Simulated-person scripts**
   - Sarah Mitchell
   - Tyler Brennan
   - Rebecca Nwosu
   - Legal and executive contacts
   - Allowed answers, facts they do not know, and escalation behavior
8. **Pacing and hint guide**
   - Pause/advance rules
   - Three hint levels
   - Handling early success or prolonged delay
9. **Technical fault procedures**
   - Retry once, use fallback, pause, or stop criteria
   - How to mark an exercise deviation
10. **Safety and emergency stop**
11. **Exercise-end and hotwash script**
12. **Run archival and reset handoff**

## Evaluator guide

1. **Evaluator role and neutrality**
2. **Learning objectives and rubric**
3. **Observation assignments**
   - Team decisions and communication
   - Splunk investigation
   - Identity/endpoint containment
   - Cloud containment and recovery
4. **Evidence-collection method**
   - Timestamped observation format
   - Event/submission references
   - Platform-fault notation
5. **Objective evaluation sheets**
   - Critical tasks
   - Performance indicators
   - Successful-state verifier
   - Rating and rationale
6. **Decision-point sheets**
   - DP1 through DP4 conditions
   - Selected branch and supporting state
7. **Hint and intervention record**
8. **Exercise-quality observations**
   - Missing or misleading evidence
   - Timing and workload
   - Technical reliability
   - Participant confusion caused by design
9. **Hotwash questions**
10. **After-action report input**
    - Strengths
    - Areas for improvement
    - Root causes
    - Recommended corrective actions

## Solution guide

1. **Ground truth and attack narrative**
2. **Initial environment state**
3. **Canonical event timeline**
4. **Expected evidence by MSEL item**
   - Relevant fields and event IDs/patterns
   - Example Splunk searches
   - False leads and benign comparison activity
5. **Recommended investigation approach**
6. **Identity containment procedure and verification**
7. **Endpoint/AD containment procedure and verification**
8. **Mock-cloud scoping and containment procedure**
9. **Impact analysis and recovery procedure**
10. **Branch-specific answers**
    - Contained/adverse identity variants
    - Limited/full cloud exposure
    - Blocked/realized safe impact
11. **Learning-objective answer key and scoring examples**
12. **Common mistakes and coaching notes**
13. **ATT&CK mapping with citations and rationale**
14. **Known prototype limitations**

## After-action report outline

Although not participant-facing, the release should include a generated or fillable AAR structure:

1. Exercise name, version, run ID, date, team, and branch path
2. Purpose, scope, and objectives
3. Exercise timeline and deviations
4. Objective ratings with supporting evidence
5. Participant strengths
6. Areas for improvement and root causes
7. Technical/platform observations
8. Participant feedback
9. Corrective actions with owner, priority, and target date
10. Exercise-design changes for the next run

## Documentation acceptance test

A person unfamiliar with the implementation should be able to:

1. prepare the environment using the deployment and safety documentation;
2. facilitate the scenario using only the facilitator guide and controller interface;
3. evaluate all five objectives using the evaluator guide;
4. reproduce the expected investigation and recovery using the solution guide; and
5. reset and validate the environment without consulting a developer.
