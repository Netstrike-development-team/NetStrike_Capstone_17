"""Verify existing help/review/archive UI in a disposable actual browser.

Synthetic test-only judgments are NOT learner evaluation or approved coaching.
Preview is inert. Explicit execution always uses managed Chromium without media.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Direct-file execution must add the repository before importing its packages.
from scripts.record_ui_walkthrough import Walkthrough, main  # pylint: disable=wrong-import-position

QUESTION = "Synthetic browser fixture: how is this sample clarification recorded?"
OTHER_QUESTION = "Synthetic browser fixture: report a platform interruption."
REPLY = "Synthetic test-only clarification; not approved coaching. <b>literal text</b>"
PLATFORM_REPLY = "Synthetic browser fixture: stopped test run, not a learner failure."
RATIONALE = "Synthetic automation fixture only; no representative learner was evaluated."
CORRECTION = "Synthetic fixture correction; no representative learner was evaluated."


class StaffWalkthrough(Walkthrough):
    """Real help, review, downloads and reset; no simulated API responses."""

    journey_id = "staff-operations"
    smoke_default = True
    role_names = Walkthrough.role_names + ("technical_operator", "evaluator")
    scenes = [(title, "Synthetic staff-browser test, not learner evaluation or range acceptance.")
              for title in (
                  "Prepare disposable exercise", "Start and pause through browser controls",
                  "Ask a private question", "Separate another participant's question",
                  "Record a facilitator clarification", "Read only the requester's reply",
                  "Stop incomplete play safely", "Record a platform-only operator reply",
                  "Inspect assistance and record a test-only judgment",
                  "Preserve a draft and append a correction", "Download pinned current review",
                  "Capture and download a frozen archive", "Reset without overwriting history",
                  "Verify empty current review and immutable saved files",
              )]

    def browser_post(self, selector, path):
        """Click the real form/control, require its successful actual response."""
        with self.page.expect_response(
            lambda response: response.url.endswith(path) and response.request.method == "POST"
        ) as pending:
            self.page.locator(selector).click()
        response = pending.value
        assert response.status == 200, f"browser POST failed: {path}"
        if path in {f"/api/facilitator/{command}" for command in ("prepare", "start", "pause", "stop", "reset")}:
            assert response.request.headers["x-exercise-run-id"] == self.run_id
        return response.json(), response.request.post_data_json

    def download(self, selector, filename):
        """Save only a task-selected filename; no trace/profile/credentials export."""
        with self.page.expect_download() as pending:
            self.page.locator(selector).click()
        pending.value.save_as(self.output / filename)
        if filename != "events.jsonl":
            self.evidence_files.append(filename)
        return self.output / filename

    def open_support(self, path, role):
        from playwright.sync_api import expect  # pylint: disable=import-outside-toplevel

        self.goto(path, role)
        self.page.locator("#support-title").click()
        with self.page.expect_response(lambda response: response.url.endswith("/support")) as pending:
            self.page.locator("#support-refresh").click()
        assert pending.value.status == 200
        expect(self.page.locator("#support-threads")).not_to_contain_text("No authorized")

    def question(self, objective, message):
        form = self.page.locator("#support-form")
        form.locator('[name="objective_id"]').select_option(objective)
        form.locator('[name="message"]').fill(message)
        receipt, body = self.browser_post("#support-send", "/api/participant/support")
        assert body["run_id"] == receipt["run_id"] == self.run_id
        assert body["message"] == message and body["objective_id"] == objective
        return receipt

    def reply(self, request_id, kind, objective, message):
        form = self.page.locator("#support-form")
        form.locator('[name="request_id"]').select_option(request_id)
        form.locator('[name="kind"]').select_option(kind)
        form.locator(f'[name="objective_ids"][value="{objective}"]').check()
        form.locator('[name="message"]').fill(message)
        receipt, body = self.browser_post("#support-send", "/api/facilitator/support/replies")
        assert body["run_id"] == receipt["run_id"] == self.run_id
        assert (body["request_id"], body["kind"], body["objective_ids"], body["message"]) == (
            request_id, kind, [objective], message
        )
        return receipt

    def judge(self, rationale, *, revision):
        from playwright.sync_api import expect  # pylint: disable=import-outside-toplevel

        form = self.page.locator("#judgment")
        form.locator('[name="objective_id"]').select_option("LO2")
        form.locator('[name="rating"]').select_option("not_observed")
        form.locator('[name="rationale"]').fill(rationale)
        form.locator('[name="evidence_ids"]').fill(self.reply_receipt["event_id"])
        form.locator('[name="platform_reason"]').fill(
            "Synthetic run deliberately stopped during browser testing; no learner grade."
        )
        if revision:
            form.locator('[name="override_reason"]').fill("Synthetic append-only correction fixture.")
        receipt, body = self.browser_post("#save", "/api/evaluator/judgments")
        assert body["run_id"] == self.run_id and body["expected_revision"] == revision
        assert body["rating"] == "not_observed" and body["objective_id"] == "LO2"
        assert receipt["revision"] == revision + 1
        expect(self.page.locator("#notice")).to_contain_text("Judgment recorded")
        expect(self.page.locator("#review-summary")).to_contain_text("1/5 objectives reviewed")
        expect(self.page.locator("#objectives")).to_contain_text(f"revision {revision + 1}")
        return receipt

    # Keep a single chronological test, reusing production browser/server cleanup.
    # pylint: disable=too-many-locals,too-many-statements
    def perform(self):
        from playwright.sync_api import expect  # pylint: disable=import-outside-toplevel

        def prepare():
            self.goto("/facilitator", "facilitator")
            self.browser_post('[data-command="prepare"]', "/api/facilitator/prepare")
            expect(self.page.locator('[data-command="start"]')).to_be_enabled()

        self.scene(0, prepare)

        def start_pause():
            def confirm(dialog):
                if dialog.type != "confirm" or not dialog.message.startswith("Start play only after"):
                    dialog.dismiss()
                    raise RuntimeError("unexpected start confirmation")
                dialog.accept()  # This task owns an isolated synthetic app, not range admission.

            self.page.once("dialog", confirm)
            self.browser_post('[data-command="start"]', "/api/facilitator/start")
            expect(self.page.locator('[data-command="pause"]')).to_be_enabled()
            self.browser_post('[data-command="pause"]', "/api/facilitator/pause")
            expect(self.page.locator("#run-state")).to_have_text("paused")

        self.scene(1, start_pause)

        def ask():
            self.open_support("/participant", "soc_analyst")
            self.question_receipt = self.question("LO2", QUESTION)
            expect(self.page.locator("#support-threads")).to_contain_text(QUESTION)

        self.scene(2, ask)

        def other_participant():
            self.open_support("/participant", "cloud_responder")
            expect(self.page.locator("#support-threads .support-thread")).to_have_count(0)
            expect(self.page.locator("#support-threads")).not_to_contain_text(QUESTION)
            self.other_receipt = self.question("LO4", OTHER_QUESTION)
            expect(self.page.locator("#support-threads .support-thread")).to_have_count(1)
            expect(self.page.locator("#support-threads")).not_to_contain_text(QUESTION)

        self.scene(3, other_participant)

        def clarify():
            self.open_support("/facilitator", "facilitator")
            expect(self.page.locator("#support-threads .support-thread")).to_have_count(2)
            self.reply_receipt = self.reply(self.question_receipt["request_id"], "clarification", "LO2", REPLY)
            expect(self.page.locator("#support-threads")).to_contain_text(REPLY)
            expect(self.page.locator("#support-threads b")).to_have_count(0)

        self.scene(4, clarify)

        def own_reply():
            self.open_support("/participant", "soc_analyst")
            expect(self.page.locator("#support-threads .support-thread")).to_have_count(1)
            expect(self.page.locator("#support-threads")).to_contain_text(REPLY)
            expect(self.page.locator("#support-threads")).not_to_contain_text(OTHER_QUESTION)
            expect(self.page.locator("#support-threads")).not_to_contain_text("demo-facilitator")
            expect(self.page.locator("#support-threads b")).to_have_count(0)

        self.scene(5, own_reply)

        def stop():
            self.goto("/facilitator", "facilitator")
            self.page.locator("#stop-reason").fill("Synthetic browser fixture: stop incomplete play.")
            self.browser_post("#stop", "/api/facilitator/stop")
            expect(self.page.locator("#run-state")).to_have_text("stopped")
            fixture = self.request("/api/participant/recovery", role="cloud_responder")["fixture"]
            assert fixture["available_originals"] == 5 and fixture["baseline_verified"]

        self.scene(6, stop)

        def operator_reply():
            self.open_support("/facilitator", "technical_operator")
            kinds = self.page.locator('#support-form [name="kind"] option').evaluate_all(
                "options => options.filter(option => !option.disabled).map(option => option.value)"
            )
            assert kinds == ["platform_issue"]
            self.platform_receipt = self.reply(self.other_receipt["request_id"], "platform_issue", "LO4", PLATFORM_REPLY)
            expect(self.page.locator("#support-threads")).to_contain_text(PLATFORM_REPLY)

        self.scene(7, operator_reply)

        def review():
            self.open_support("/evaluator", "evaluator")
            expect(self.page.locator("#support-form")).to_have_count(0)
            expect(self.page.locator("#support-threads .support-thread")).to_have_count(2)
            expect(self.page.locator("#support-threads")).to_contain_text(REPLY)
            expect(self.page.locator("#support-threads")).to_contain_text(PLATFORM_REPLY)
            self.judge(RATIONALE, revision=0)

        self.scene(8, review)

        def correct():
            form = self.page.locator("#judgment")
            form.locator('[name="objective_id"]').select_option("LO2")
            form.locator('[name="rationale"]').fill("Synthetic unsaved draft")
            old_card = self.page.locator("#objectives > article").first.element_handle()
            with self.page.expect_response(lambda response: response.url.endswith("/api/evaluator/report")):
                self.page.locator("#refresh").click()
            self.page.wait_for_function("node => !node.isConnected", arg=old_card)
            expect(form.locator('[name="rationale"]')).to_have_value("Synthetic unsaved draft")
            self.judge(CORRECTION, revision=1)

        self.scene(9, correct)

        def current_exports():
            from orchestrator.aar import build_report, render_markdown, validate_bundle  # pylint: disable=import-outside-toplevel

            report = self.request("/api/evaluator/report", role="evaluator")
            for selector, name in (("#bundle", "current-bundle.json"), ("#aar", "current-aar.md")):
                with self.page.expect_response(lambda response: "/api/evaluator/exports/" in response.url) as pending:
                    self.download(selector, name)
                assert pending.value.status == 200
                headers = pending.value.request.headers
                assert headers["x-exercise-run-id"] == self.run_id
                assert headers["x-review-bundle-sha256"] == report["bundle_sha256"]
            bundle = json.loads((self.output / "current-bundle.json").read_text())
            validate_bundle(bundle)
            assert bundle["run_id"] == self.run_id and bundle["run_state"] == "stopped"
            for event_type, roles in (
                ("exercise.support.requested", ["soc_analyst", "cloud_responder"]),
                ("exercise.support.responded", ["facilitator", "technical_operator"]),
                ("evaluation.objective.judged", ["evaluator", "evaluator"]),
            ):
                actual = [event for event in bundle["events"] if event["event_type"] == event_type]
                assert [event["actor"]["role"] for event in actual] == roles
                assert [event["actor"]["id"] for event in actual] == ["demo-" + role for role in roles]
            responses = [event for event in bundle["events"] if event["event_type"] == "exercise.support.responded"]
            assert [event["event_id"] for event in responses] == [
                self.reply_receipt["event_id"], self.platform_receipt["event_id"]
            ]
            assert [event["correlation_ids"] for event in responses] == [
                [self.question_receipt["request_id"]], [self.other_receipt["request_id"]]
            ]
            rebuilt = build_report(bundle)
            objective = next(item for item in rebuilt["objectives"] if item["objective_id"] == "LO2")
            assert len(objective["history"]) == 2 and objective["judgment"]["rating"] == "not_observed"
            assert rebuilt["reviewed_objectives"] == 1 and rebuilt["aggregate_score"] is None
            assert (self.output / "current-aar.md").read_text() == render_markdown(rebuilt)

        self.scene(10, current_exports)

        def archive():
            from orchestrator.aar import build_report, render_markdown, validate_bundle  # pylint: disable=import-outside-toplevel

            self.page.locator(".archive-panel > summary").click()
            self.page.locator("#archive-prepare").click()
            expect(self.page.locator("#archive-capture")).to_be_enabled()
            receipt, body = self.browser_post("#archive-capture", "/api/evaluator/archives")
            self.archive_id = receipt["metadata"]["archive_id"]
            assert body["run_id"] == receipt["metadata"]["run_id"] == self.run_id
            selector = f'button[data-archive="{self.archive_id}"]'
            self.page.locator(selector + '[data-suffix="report"]').click()
            expect(self.page.locator("#saved-review")).to_contain_text(CORRECTION)
            for suffix, filename in (("bundle.json", "archive-bundle.json"), ("aar.md", "archive-aar.md"),
                                     ("events.jsonl", "events.jsonl")):
                self.download(selector + f'[data-suffix="{suffix}"]', filename)
            bundle = json.loads((self.output / "archive-bundle.json").read_text())
            validate_bundle(bundle)
            assert bundle == json.loads((self.output / "current-bundle.json").read_text())
            assert (self.output / "archive-aar.md").read_text() == render_markdown(build_report(bundle))
            assert [json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()] == bundle["events"]
            self.validate_ledger()

        self.scene(11, archive)

        def reset():
            self.goto("/facilitator", "facilitator")
            self.page.locator("#new-run-id").fill(self.run_id + "-fresh")
            self.page.once("dialog", self.confirm_reset)
            receipt, _body = self.browser_post("#reset", "/api/facilitator/reset")
            assert receipt["reset"]["prior_run_id"] == self.run_id
            expect(self.page.locator("#run-id")).to_have_text(self.run_id + "-fresh")
            expect(self.page.locator("#run-state")).to_have_text("ready")

        self.scene(12, reset)

        def historical_after_reset():
            self.open_support("/evaluator", "evaluator")
            expect(self.page.locator("#review-summary")).to_contain_text(self.run_id + "-fresh")
            expect(self.page.locator("#review-summary")).to_contain_text("0/5 objectives reviewed")
            expect(self.page.locator("#support-threads .support-thread")).to_have_count(0)
            expect(self.page.locator("#objectives")).not_to_contain_text(CORRECTION)
            expect(self.page.locator("#judgment [name=rationale]")).to_have_value("")
            expect(self.page.locator("#save")).to_be_disabled()
            self.page.locator(".archive-panel > summary").click()
            selector = f'button[data-archive="{self.archive_id}"]'
            self.page.locator(selector + '[data-suffix="report"]').click()
            expect(self.page.locator("#saved-review")).to_contain_text(CORRECTION)
            for suffix, before, after in (
                ("bundle.json", "archive-bundle.json", "after-reset-bundle.json"),
                ("aar.md", "archive-aar.md", "after-reset-aar.md"),
                ("events.jsonl", "events.jsonl", "after-reset-events.jsonl"),
            ):
                self.download(selector + f'[data-suffix="{suffix}"]', after)
                assert (self.output / before).read_bytes() == (self.output / after).read_bytes()
            expect(self.page.locator("#judgment [name=rationale]")).to_have_value("")
            expect(self.page.locator("#save")).to_be_disabled()
            self.open_support("/participant", "soc_analyst")
            expect(self.page.locator("#support-threads .support-thread")).to_have_count(0)
            expect(self.page.locator("#support-send")).to_be_disabled()

        self.scene(13, historical_after_reset)
        self.completed_checks = {
            "play_completed": False, "run_stopped": True, "baseline_decoys_unchanged": True,
            "synthetic_review_fixture": True, "learner_evaluation_performed": False,
            "private_help_checked": True, "operator_platform_reply_checked": True,
            "append_only_review_checked": True, "snapshot_pinned_downloads_checked": True,
            "archive_after_reset_checked": True, "application_reset_verified": True,
            "mobile_evidence_checked": False,
            "ledger_scope": "frozen archive before capture audit and application reset",
        }


if __name__ == "__main__":
    main(walkthrough_type=StaffWalkthrough)
