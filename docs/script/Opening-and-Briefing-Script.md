# Operation Silent Spider — opening and 15-minute briefing

Facilitator working draft, revised 14 October 2026. Builds on Anna's opening
message and the expanded briefing supplied by Aya. Anna retains content approval.
Checked against application source `a5725fa97d70ef8e4e9934498646427494494b6a`.
This is not a record of a completed rehearsal or deployment acceptance.

Read the quoted paragraphs aloud. Unquoted directions are staff notes, not
participant dialogue. Complete the [delivery checklist](README.md) first.
Give participants only the [quick reference](Participant%20Quick%20Reference.md),
not the staff design package, solution guide or raw evaluator exports.

## Timing

The opening is part of the briefing, not an extra introduction.

| Briefing time | Topic |
| --- | --- |
| 00:00–01:30 | Welcome, schedule and team roles |
| 01:30–04:00 | Ground rules and emergency stop |
| 04:00–06:00 | SimCorp and service overview |
| 06:00–09:00 | Splunk and portal access demonstration |
| 09:00–11:00 | Approved response controls and help |
| 11:00–14:00 | Required outputs and evidence conventions |
| 14:00–15:00 | Access check, questions and start |

Allow time for clicks and questions. Use harmless orientation records, not the
incident answer key. These are rehearsal targets, not measured speaking times.

## 1. Welcome — 00:00–01:30

> Welcome, everyone, and thanks for being here. I'm [FACILITATOR_NAME], and joining me are [STAFF_NAMES_AND_ROLES]. We'll be guiding you through Operation Silent Spider.
>
> Today, you're SimCorp's incident response team. SimCorp is fictional, and all scenario identities and business data are synthetic. Your job is to work together, investigate the information you receive, make response decisions, and explain your reasoning as the situation develops.
>
> The session is 2 hours and 50 minutes: this 15-minute briefing, 2 hours and 10 minutes of exercise play, and a 25-minute debrief. I'll announce when play starts; the exercise clock will start and the first SimCorp message will arrive in the portal. Don't begin response actions before that announcement.
>
> Choose an incident lead and note-taker, and divide investigation and response work between you. You can combine roles. Keep sharing what you find so nobody acts on an outdated assumption.
>
> This is a learning exercise, not a race or public leaderboard. We'll review your evidence, decisions, response actions and communication. You can ask for help.

Confirm the team has assigned investigation, identity/endpoint response and
cloud/recovery work. Functional team roles do not grant portal permissions;
Patrick/Aya must supply the appropriate participant credentials separately.

## 2. Ground rules and emergency stop — 01:30–04:00

> Work only with the approved exercise systems and targets listed in your handout. You may search and export permitted exercise events, inspect the supplied records, preserve copies and hashes in [EVIDENCE_DIRECTORY], and use the approved response controls. Explain why you're taking a disruptive action and preserve relevant evidence first.
>
> Don't connect to systems outside the exercise scope, contact real people, use real personal data or credentials in scenario records, alter source logs, install unapproved tools, or disable safety controls. Don't change Splunk, the controller, evaluator settings or VM snapshots. Never encrypt or erase real data.
>
> If you see anything unsafe, unexpected external connectivity, a target outside our scope, or a change to unrelated data, say **“STOP EXERCISE”** immediately and contact [SAFETY_CONTACT]. Anyone may call a stop. Stop typing commands and stop submitting actions; leave the screens, logs and files as they are. Don't try to clean up or reset anything yourself.
>
> Staff will confirm the stop and tell you what happens next. If the portal isn't responding, contact us directly; don't wait for the help queue. Don't continue until the facilitator explicitly gives instructions. A tool failure is not automatically a participant mistake.

Staff procedure, not extra participant dialogue:

1. Acknowledge the call verbally and tell all participants to stop actions.
2. The authenticated facilitator or technical operator enters a reason in the
   `/facilitator` control panel and presses **Emergency stop**. Inspect the run
   state and cleanup/audit diagnostics; a click or silent page is not confirmation.
3. If the service is unreachable or effects continue, use Patrick's tested
   external range stop procedure and contact the named on-duty technical operator.
   Zian/Julien are escalation contacts, not an assumed live emergency channel.
4. Preserve evidence and record the time, reason and affected systems. Do not
   reset or restore snapshots before exporting required evidence outside the VMs.
5. Distinguish a reversible pause from a terminal emergency stop. A stopped or
   fault-latched run must not simply be resumed; follow the documented recovery,
   archive/reset and readiness procedure before a fresh run.

Do not claim that the application stop forcibly cancels a stuck handler or
undoes work already completed. Confirm the external procedure before delivery.

## 3. SimCorp and the service map — 04:00–06:00

> SimCorp is a fictional services company preparing a quarterly customer billing export. You'll be supporting its staff while investigating an incident. Sarah Mitchell is the VP of Finance, Tyler Brennan is a helpdesk technician, and Rebecca Nwosu is the Director of IT. Simulated staff conversations go through exercise control, not real calls or emails.
>
> Your handout includes short policies for identity and access, helpdesk verification, data handling and escalation. Use those policies to understand what normal, authorized activity should look like. They aren't an answer key.
>
> The map shows services, not necessarily seven separate VMs. Identity handles accounts, sessions and MFA. Helpdesk holds support records. The Finance workstation and directory provide endpoint and account context. The mock cloud holds synthetic storage records, and the recovery service supplies disposable files and their known-good backup.
>
> Splunk is the investigation tool. The participant portal receives situation updates, records your findings and exposes approved response controls. The cloud is a local Python simulation, not AWS. Portal response actions change controlled simulation state; don't assume they administer real Windows or Active Directory services.

Show the conceptual map in the quick reference, followed by Patrick's approved
participant topology if available. Do not present the repository's example
subnet, URLs or logical-to-VM mapping as a confirmed deployment.

## 4. Access demonstration — 06:00–09:00

Before this section, workstations should be ready. Never assume OS login also
authenticates Splunk or the portal. Do not project passwords or access tokens.

### Splunk: demonstrate a neutral search

> Open [SPLUNK_URL_OR_SHORTCUT] and sign in using the private access instructions. Open [SPLUNK_APP]. Set the time picker to [SPLUNK_UTC_WINDOW], including the supplied pre-exercise history. Use the exact learner search from your handout; it is restricted to your assigned exercise and run.
>
> Open one harmless orientation event and find its time, source and event identifier. A received time and the time something happened can be different. Record occurrence times with their time zone.
>
> If you get no results, check the supplied time window and run filter, then tell us. No results do not prove that nothing happened. Don't remove scope restrictions or change server configuration to fix access.

Patrick must validate the handout's base search, extracted fields, event-ID
mapping and participant permissions on the actual deployment. Use the neutral
count/table examples in the handout, not searches that identify the culprit.
This is a short refresher, not a replacement for introductory Splunk training.

### Participant portal: demonstrate connection and navigation

> Open [PORTAL_BASE_URL]/participant. Paste your assigned participant token into **Exercise access token**, then select **Connect**. Check the **Run ID** against your handout. New SimCorp messages appear under **Situation updates**; use **Refresh** if needed.
>
> **Open evidence timeline** opens the local, read-only synthetic evidence viewer. It is not Splunk. Connect there with your assigned participant token as well. You can filter signals and copy event IDs for your submissions.

The current UI has no team-name banner, inject-acknowledgement button or
attachment-upload form. Do not tell learners to find them. Acknowledgement and
ordinary status updates use [TEAM_UPDATE_CHANNEL], with staff recording them.
Do not silently replace unavailable Splunk with the local viewer: disclose and
record any approved fallback and its effect on what can fairly be evaluated.

## 5. Response controls and help — 09:00–11:00

Point to the controls without executing incident actions during the briefing.

> **Approved containment actions** is where you act on evidence-supported targets. Depending on your assigned permissions, you can revoke a session, remove an MFA factor, rotate a credential, preserve evidence, isolate a host's simulated remote path, or remove designated persistence and stop the synthetic impact task. Cloud controls preserve evidence, revoke a key or disable its principal, and restore the approved policy.
>
> Use the identifiers you actually find, not guessed targets. Coordinate actions with your team, inspect the result, and verify the current state. An accepted request alone doesn't prove containment succeeded. Don't repeat an action just because a response was slow or lost; inspect and ask staff first.
>
> For a question or tool problem, expand **Ask exercise staff for help**, choose the related learning objective, write your question, and select **Send help request**. Staff reply manually. Use **Refresh replies** to check. This thread is private to you and authorized staff, so share relevant guidance with your teammates.
>
> If an otherwise valid action isn't supported, describe it there and ask the facilitator whether it can be simulated. A request doesn't execute the action. Help is recorded for human review; it does not automatically deduct points. Technical problems are considered separately from coaching. For anything urgent or unsafe, contact us directly instead.

One help request per actor can be pending at a time. Replies are not guaranteed
within a fixed time; assign someone to monitor the queue. Record any off-platform
assistance and simulated action separately. Requests do not change branch state.

## 6. What to submit — 11:00–14:00

Show each section briefly; do not fill it with the scenario solution. The quick
reference supplies working templates, including an offline note-taking fallback.

> You'll submit four pieces of written work through the portal and maintain a team decision log.
>
> First, **Initial assessment**: identify the affected identity, choose your classification, and give at least three evidence references from at least two sources. Use event, ticket or artifact IDs and identify the source. There's no file-upload button; keep exported evidence in the approved folder and cite it.
>
> Second, **Submit your intrusion timeline**: record at least six significant events using occurrence times with a time zone, supporting event IDs and short descriptions. Mark each statement as **Observed fact** or **Analyst inference**. Put the events in order and explain uncertainty rather than filling gaps with guesses.
>
> Third, when available, the **Cloud assessment**: identify the affected service principal, count the records confirmed accessed, choose the conclusion supported by the evidence, and cite current-run cloud audit event IDs. Include the affected bucket and your containment rationale in your team notes. Access to synthetic records, or a claim of theft, doesn't by itself prove external transfer.
>
> Finally, **Final incident brief**: state confirmed scope, confirmed cloud-record count, business impact, actions taken, remaining risk, and at least two prioritized recommendations. Cite the recovery audit evidence supporting your conclusion.
>
> For recovery, **Preview only — do not execute** starts checked. A preview is not a restore. Inspect the preview first, then deliberately execute approved recovery and hash validation when appropriate. Verify what actually recovered before reporting success.
>
> Keep recording who decided what, when, why and with what result. Submit before play ends; don't leave everything until the last minute. Drafts are not a saved submission. Staff will stop technical play at the end, collect your work and lead a 25-minute discussion of what happened and what we can learn.

Portal forms already exist for the timeline and final brief; Anna need not
invent new UI templates. The current timeline supports 6–12 entries. Cloud and
recovery sections require the full-play scenario to be enabled. Free-text status
updates, arbitrary file attachments and a separate decision-log form are not
implemented; use the agreed channel and evidence folder.

Use UTC in submitted notes/timeline entries. Portal situation-update timestamps
may display in browser-local time. The exercise clock is elapsed scenario time,
not the timestamp to paste into an incident timeline. After an observed reset or
credential change, old drafts clear; do not resubmit material into a different run.

## 7. Final check and start — 14:00–15:00

> Before we start: can everyone access their assigned tools, see the correct Run ID, find the evidence folder, and explain how to call a safety stop? Does everyone know who is coordinating the team and where to submit findings?
>
> Any last access or process questions? If something isn't working, tell us now.
>
> Once we're ready, I'll announce the start. Read the first situation update together, decide your initial priorities, and follow the evidence. You don't need to guess the whole story immediately.

Do not start until local and external admission checks are complete. Announce
**“Exercise play starts now”**, start the controller and verify the first message
arrives. Record the actual start and planned end. If delivery fails, treat it as
a platform problem rather than silently consuming participants' play time.

At end of play, announce **“Exercise play has ended; stop technical actions.”**
Collect the submitted work and team notes, preserve staff evidence privately,
then begin the 25-minute hotwash. Do not expose facilitator answers early.
