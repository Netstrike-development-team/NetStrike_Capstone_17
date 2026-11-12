# Briefing materials — author review and delivery checklist

Revised 14 October 2026. Supports Anna's #99 participant-materials work, with
related authored content under #98/#100. These local revisions are drafts,
not issue closure, teammate acceptance or authorization to promote to main.

## Files and intended audience

- [Opening and 15-minute briefing](Opening-and-Briefing-Script.md): facilitator read-aloud script plus private delivery notes. Renamed with a Markdown extension so applications can recognize and open it.
- [Printable briefing PDF](Operation-Silent-Spider-Opening-and-Briefing.pdf): convenient export of the same facilitator draft. The Markdown is the editable source; regenerate the PDF after approved script changes.
- [Participant quick reference](Participant%20Quick%20Reference.md): learner-safe handout, conceptual map, working templates and neutral Splunk examples. Complete placeholders and obtain approval before distributing.

Read-aloud text is quoted. Do not distribute staff notes, the solution guide,
full MSEL, checkpoint verifiers, evaluator archive or raw canonical staff ledger
to participants. Do not copy answer-bearing screenshots into this handout.

## What Anna added and what this review changes

Anna directly added/edited the opening on `dev` in commits `4c8efdb`, `6380715`,
`f64efe0` and `a5725fa` (11–13 October). At `a5725fa`, the file is a 17-line
opening only. The expanded briefing pasted into chat was reviewed as additional
draft content, not misreported as already committed by Anna. No recent Anna PR
or her own new acceptance comment was found in #98–#100 during this review.

The revision preserves her welcome and approved duration, and adds/fixes:

- The opening is included within the 15-minute briefing; play is 130 minutes,
  with 25 minutes for hotwash. A timed table-read remains required.
- Rebecca Nwosu is Director of IT, as recorded in the maintained synthetic
  profiles—not an invented role. The billing-export background does not invent
  a new “next week” deadline.
- A participant safety call plus actual staff Emergency stop workflow and an
  external escalation requirement. A help message is not an emergency stop.
- Actual portal labels and token connection, without imaginary uploads,
  acknowledgement/team-name/status/simulated-action buttons.
- Private manual help, separate technical problems, no promised reply deadline
  and no automatic point deduction.
- Existing timeline and incident-brief forms, cloud assessment, approved
  response controls, evidence/decision-log templates and recovery preview rules.
- UTC/occurrence-time versus receipt/browser time, source/run correlation,
  uncertain-delivery guidance and the simulation-versus-live-system boundary.
- Draft short fictional policies and a conceptual map, explicitly pending
  content/deployment approval instead of silently inventing final facts.

## Required before exercise delivery

### Anna — content and participant experience

- [ ] Approve or revise spoken text and quick reference against final MSEL/witness content.
- [ ] Approve the four short fictional policies, including a usable trusted helpdesk verification/contact route; no real contacts or answer key.
- [ ] Agree how participants acknowledge messages and give ordinary status updates; no UI acknowledgement is currently implemented.
- [ ] Run a timed read-aloud/click-through within 15 minutes, including the opening and questions; record actual timing and revisions.
- [ ] Have at least one non-author use the materials and portal without code explanations. Record confusion, defects and resolutions/accepted limitations under #99.
- [ ] Align facilitator/evaluator/solution guidance and assistance treatment under #100; no automatic numeric score or calibration claim.

### Patrick — deployment and tool walkthrough

- [ ] Confirm actual URLs/shortcuts, Splunk app, private login instructions, participant role permissions and current tested source revision.
- [ ] Supply the learner-safe base search and verify it with participant credentials, including index/sourcetype, extracted exercise/run fields and current-run event IDs.
- [ ] Confirm the absolute time window covers the backdated history and live play; document Splunk/browser time zones and `_time` mapping.
- [ ] Verify actual application-event arrival separately from Windows Sysmon arrival. A successful older offline installation is not proof of current application ingestion.
- [ ] Test that participant access cannot retrieve facilitator/evaluator/internal events or another team's data. A user-entered `visibility` or `run_id` filter is not authorization.
- [ ] Supply the approved scope, evidence folder, participant-facing VM/service map and any allowed direct host administration. The example topology is not final approval.
- [ ] Test staff Emergency stop and the external range procedure if the app is unreachable. Supply an on-duty contact and escalation route.
- [ ] Provide deployment screenshots with no tokens, private staff data, answers or hidden branch criteria. Use harmless orientation records.

Recommended screenshots are Splunk app navigation, time picker, an approved
neutral event, portal connection/run status, Situation updates, help panel, a
blank timeline/cloud assessment and a blank final brief. There are no upload or
acknowledgement screenshots to supply. Aya can capture the application screens;
Patrick supplies the deployed Splunk/environment screens.

The event contract recommends `netstrike:event:v1` and `ns_run_id`/`ns_event_id`
aliases, but those names are not claimed as deployed. Windows event channels
can have different fields and run-scoping methods. Don't paste staff-only
contract searches unmodified into the participant card. Don't rely on
participant-authored filters to protect a mixed-visibility raw ledger.

### Ashley — delivery coordination

- [ ] Confirm staff roster, session start/end, breaks, urgent/backup contact method and ordinary team-update channel.
- [ ] Coordinate any missing range decisions/dates with Latifa and technical questions with Zian/Julien.
- [ ] Confirm the approved fallback for unavailable tools, and how a pause/fault affects the remaining play time and the 170-minute booking. Record deviations rather than silently shortening play or extending the session.

### Aya — application integration

- [ ] Verify the delivered source still uses the labels/forms cited here; enable the full-play scenario, not only the default identity slice.
- [ ] Supply role-appropriate tokens privately and demonstrate successful connection on each needed page without recording secrets.
- [ ] Fix evidenced application defects; integrate Anna-approved scenario text through a reviewed change rather than treating this document as new runtime content.
- [ ] Preserve independent review and main-promotion gates. These revisions do not complete #153 or participant/range acceptance.

## Review receipt — fill with observed results, not estimates

```text
Script/handout revision:
Application source commit and scenario:
Anna content approval / unresolved wording:
Patrick deployment revision / confirmed URLs, role and fields:
Staff roster and tested urgent-contact/stop procedure:
Timed briefing date, actual duration, revisions:
Non-author participant, date, tasks attempted and observed confusion:
Defects, owner, fix/retest or accepted limitation:
Approved fallback and any effect on assessment/session duration:
Delivery approval and remaining blockers:
```

## Sources and boundaries

Local documentation checks on 14 October: whitespace diff check passed; ten
relative links resolved; code fences balanced; 20 cited participant UI labels
matched the source; the handout contained none of the checked hidden checkpoint
or solution identifiers. Read-aloud paragraphs contain approximately 1,287 words
(about ten minutes at 130 words/minute), leaving roughly five minutes for clicks,
questions and transitions. This estimate is not a timed rehearsal or usability
acceptance. No application source was changed or application test pass inferred.
The five-page PDF was reopened for text checks and all pages rendered for visual
inspection; spoken paragraphs stay together across page breaks.

Checked against `dashboard/static/participant.html`, `participant.js`,
`evidence.html`, `docs/exercise-support.md`, `docs/staff-operations.md`,
`docs/after-action-review.md`, the event contract and approved exercise design.
Rebecca's role is in `orchestrator/fixtures/identity-profiles.v1.json`.
Generic Splunk commands/navigation were checked against the official 10.0
references linked in the handout; actual Splunk Enterprise 10.0.1 deployment
still needs Patrick's validation.

Useful private author references: [charter](../exercise-design/01-exercise-charter.md),
[safety](../exercise-design/04-safety-and-reset.md),
[support](../exercise-support.md), [staff operations](../staff-operations.md),
and [main-promotion checklist](../milestone-release-checklist.md).
