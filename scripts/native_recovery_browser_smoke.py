"""Actual browser native-file recovery smoke; not Windows or learner acceptance."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.record_ui_walkthrough import Walkthrough, main  # pylint: disable=wrong-import-position


class NativeRecoveryWalkthrough(Walkthrough):
    """Use normal OS copy, real portal forms, a real verifier and immutable exports."""

    journey_id = "native-file-recovery"
    smoke_default = True
    recovery_mode = "native_files"
    scenes = [(title, "Synthetic native file recovery; Windows access is not validated.")
              for title in ("Reach marker-only impact", "Restore with the OS file tool",
                            "Verify actual files without portal restore", "Submit a recovery brief",
                            "Complete, export and reset without reusing evidence")]

    def fixture_hashes(self):
        root = self.decoy_root / self.run_id
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob("*") if path.is_file()}

    def perform(self):
        from playwright.sync_api import expect  # pylint: disable=import-outside-toplevel

        def impact():
            self.control("prepare")
            self.control("start")
            self.request("/api/participant/checkpoints/dp1", role="soc_analyst", payload={
                "affected_identity": "sarah", "classification": "account compromise",
                "evidence": [{"reference_id": reference, "source": source} for reference, source in
                             (("HD-1042", "helpdesk"), ("factor-red-01", "identity"),
                              ("sess-red-01", "identity"))]})
            for seconds, checkpoint in ((3600, "dp2"), (5700, "dp3"), (6600, "dp4")):
                self.control("advance", {"elapsed_seconds": seconds})
                self.control("checkpoints/" + checkpoint)
            self.pause()
            self.goto("/participant", "cloud_responder")
            self.page.locator("#load-recovery").click()
            expect(self.page.locator("#recovery-summary")).to_contain_text("0/5")
            expect(self.page.locator("#recovery-restore")).to_be_hidden()
            expect(self.page.locator("#recovery-mode")).to_contain_text("normal file tools")
            expect(self.page.locator("#recovery-mode")).to_contain_text("does not restore")
            self.page.locator("#recovery-mode").scroll_into_view_if_needed()

        self.scene(0, impact)

        def copy_files():
            root = self.decoy_root / self.run_id
            state = self.request("/api/participant/recovery", role="cloud_responder")
            for name in state["fixture"]["expected_manifest"]:
                subprocess.run(["/bin/cp", str(root / "known-good" / name), str(root / "live" / name)],
                               check=True, timeout=5)  # nosec B603
            self.restored_hashes = self.fixture_hashes()
            self.page.locator("#load-recovery").click()
            expect(self.page.locator("#recovery-summary")).to_contain_text("5/5")
            expect(self.page.locator("#recovery-restore")).to_be_hidden()
            self.page.locator("#recovery-summary").scroll_into_view_if_needed()

        self.scene(1, copy_files)

        def verify():
            self.page.locator('#recovery-actions [name="fixture_id"]').fill("FILE01-disposable-fixture")
            self.page.locator("#recovery-preview").uncheck()
            expect(self.page.locator("#recovery-validate")).to_have_text("Verify restored files")
            self.recovery_action("recovery.health.validate")
            assert self.fixture_hashes() == self.restored_hashes
            state = self.request("/api/participant/recovery", role="cloud_responder")
            event = state["audit"][-1]
            assert event["event_type"] == "recovery.files.verified"
            assert not event["data"]["files_modified_by_verifier"]
            assert not event["data"]["intended_user_access_verified"]
            self.health_id = event["event_id"]
            self.page.locator("#load-recovery").click()
            expect(self.page.locator("#recovery-audit")).to_contain_text("recovery.files.verified")
            self.page.locator("#recovery-audit").scroll_into_view_if_needed()

        self.scene(2, verify)

        def brief():
            form = self.page.locator("#recovery-brief")
            for name, value in {
                "confirmed_scope": "Synthetic native file-recovery browser fixture.",
                "confirmed_cloud_records": "25",
                "business_impact": "Five disposable files were unavailable.",
                "actions_taken": "Copied protected fixture backup using an OS file utility and verified bytes.",
                "remaining_risk": "Windows permissions and intended-user access remain unverified.",
                "recommendations": "Test the real learner file path.\nValidate the intended user's access.",
                "evidence_ids": self.health_id,
            }.items():
                form.locator(f'[name="{name}"]').fill(value)
            self.resume()
            self.page.locator("#refresh").click()
            with self.page.expect_response(lambda response: response.url.endswith("/recovery/brief")) as pending:
                form.locator('button[type="submit"]').click()
            assert pending.value.status == 200
            self.pause()
            form.scroll_into_view_if_needed()

        self.scene(3, brief)

        def finish_reset():
            self.advance(7800)
            state = self.request("/api/facilitator/state")
            assert state["controller"]["state"] == "completed"
            assert state["impact"]["final_review"]["passed"]
            self.goto("/facilitator", "facilitator")
            with self.page.expect_download() as pending:
                self.page.locator("#download-jsonl").click()
            pending.value.save_as(self.output / "events.jsonl")
            self.validate_ledger()
            self.page.locator("#new-run-id").fill(self.run_id + "-fresh")
            self.page.once("dialog", self.confirm_reset)
            with self.page.expect_response(lambda response: response.url.endswith("/reset")) as reset:
                self.page.locator("#reset").click()
            assert reset.value.status == 200
            fresh = self.request("/api/participant/recovery", role="cloud_responder")
            assert fresh["recovery"]["mode"] == "native_files"
            assert fresh["fixture"]["baseline_verified"] and not fresh["audit"]
            assert self.request("/api/facilitator/state")["impact"]["final_review"] is None

        self.scene(4, finish_reset)
        self.completed_checks = {"play_completed": True, "native_files_restored": True,
                                 "portal_restore_hidden": True, "verification_read_only": True,
                                 "application_reset_verified": True, "windows_access_verified": False}


if __name__ == "__main__":
    raise SystemExit(main(walkthrough_type=NativeRecoveryWalkthrough))
