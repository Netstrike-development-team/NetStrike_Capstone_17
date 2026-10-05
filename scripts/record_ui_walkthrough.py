"""Record a real, disposable localhost exercise walkthrough; no mocked API replies.

Recording-only dependencies: playwright, imageio-ffmpeg; Chrome installed locally.
macOS `say` provides optional offline narration. Default invocation is preview only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# Narration is prose; keeping each scene together makes editorial review easier.
# pylint: disable=line-too-long
SCENES = [
    (
        "Exercise control",
        "This is Operation Silent Spider, our working blue-team exercise prototype. Everything shown is running locally against synthetic identities, a Python cloud mock and five disposable files. This walkthrough uses the actual application, not slides. Splunk and the Cyber Range virtual machines are not connected here.",
    ),
    (
        "Prepare the environment",
        "Before learners arrive, exercise control prepares the reviewed scenario. The application stages incident history, verifies the synthetic profiles and prepares known-good recovery files. These setup actions are recorded. The briefing and hotwash are facilitated separately; technical play lasts one hundred and thirty exercise minutes.",
    ),
    (
        "First MFA signal",
        "Exercise control starts play and advances the clock to the first scheduled MFA request. This is the employee-facing SimCorp page. The request is real within our contained simulation, but it never contacts a real identity provider or device. We pause the exercise clock while inspecting the screen.",
    ),
    (
        "Respond to the request",
        "The simulated employee denies the unexpected request. That decision is recorded by the server. Denying a new prompt does not remove a session or factor that was compromised earlier. The exercise deliberately begins with incident history already present, so the blue team still needs to investigate.",
    ),
    (
        "Receive the incident",
        "The participant response console receives two situation updates: repeated MFA prompts and a suspicious helpdesk reset ticket. These are exercise messages, not the attack logs. Participants also have approved response controls and a link to the new local evidence timeline.",
    ),
    (
        "See the compromised session",
        "We advance to the compromised-session replay. The local evidence timeline now shows actual synthetic authentication and workstation-access events, including the affected session, host and reserved source address. These are generated records with copyable event identifiers. This view is explicitly labelled local evidence, not Splunk.",
    ),
    (
        "Submit the initial assessment",
        "At the first checkpoint, the participant identifies Sarah's account compromise and cites the helpdesk ticket, unauthorized factor and compromised session. The response is submitted through the browser and retained by the backend. For this demonstration, we leave the compromised access path open so later attack stages remain visible.",
    ),
    (
        "Follow endpoint activity",
        "As play advances, the simulator emits process discovery, directory enumeration and designated persistence activity. Filtering the timeline to endpoint evidence makes the sequence easier to follow. These are safe reviewed actions against mock state, not arbitrary commands executed on your computer.",
    ),
    (
        "Preserve evidence",
        "An endpoint responder preserves the designated synthetic evidence bundle through an approved action. The evidence viewer shows that responder's own successful receipt. It does not expose another user's private action receipts or facilitator grading checks. Preservation records evidence; it does not itself contain the attack.",
    ),
    (
        "Investigate the cloud mock",
        "After the containment checkpoint is missed, play moves into the Python cloud mock. The timeline shows service-key activity, object access and a policy change. Participants can inspect the synthetic objects and audit history. No real cloud tenant, customer record or external destination is used.",
    ),
    (
        "Establish the observed scope",
        "We let the bulk-access branch occur for the walkthrough. The audit records twenty-five synthetic customer records accessed inside the mock. A synthetic extortion claim follows. The learner must separate what the audit proves from what an attacker claims: mock access is not evidence of external transfer.",
    ),
    (
        "Apply a cloud response",
        "The cloud responder preserves evidence and revokes the exposed service key. These are real state changes in the mock, made through the participant interface. The response receipts are visible in the timeline. Revoking a key changes access controls, but does not erase the earlier confirmed access or undo its recorded scope.",
    ),
    (
        "Observe safe file impact",
        "At the prevention checkpoint, the pre-staged synthetic task remains active, so the adverse marker branch runs. Five disposable originals become unavailable in the live fixture, while their unchanged bytes remain in controlled staging. Known-good copies stay intact. No encryption, production data or real operating-system impact is involved.",
    ),
    (
        "Preview recovery first",
        "The recovery form defaults to preview. We request a restore without executing it, and the backend returns a preview receipt. Notice that the files remain unavailable. A preview does not restore files, perform a health check or earn recovery-verification credit. Execution requires an explicit choice.",
    ),
    (
        "Restore and verify",
        "The responder now explicitly restores the five decoys, then validates their hashes. The recovery view reports five originals available, unchanged originals and an intact baseline. A real health-verification event is recorded. This gives the participant evidence they can cite, rather than simply claiming recovery succeeded.",
    ),
    (
        "Communicate the incident",
        "The participant submits a final incident brief: confirmed scope, business impact, actions taken, remaining uncertainty and two follow-up recommendations. The brief cites the actual health-verification event and the confirmed mock record count. The application checks structure and observable evidence; a human evaluator still judges the quality of the report.",
    ),
    (
        "End play and retain evidence",
        "Exercise control advances to the end of technical play. Recovery observations are frozen, and the canonical event ledger is downloaded for later review or ingestion. This is not the final scoring and after-action-report implementation. It is a working integrated exercise with real local evidence from preparation through recovery.",
    ),
    (
        "Return to a clean application run",
        "Finally, exercise control resets the application into a fresh run. The old disposable fixture is restored and verified before the new run is admitted, while prior evidence remains archived. This is application reset, not virtual-machine restoration. Cyber Range snapshots, live Splunk ingestion and representative learner acceptance still need the team's deployment rehearsal.",
    ),
]
# pylint: enable=line-too-long


def checked(command, **kwargs):
    """Run a task-owned process without shell interpolation."""
    return subprocess.run(command, check=True, **kwargs)


def subtitle_time(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def local_request_url(base, path):
    """Bearer/payload requests are confined to the task-owned IPv4 HTTP listener."""
    try:
        if (not isinstance(base, str) or not isinstance(path, str)
                or any(ord(char) <= 32 or ord(char) >= 127 for char in base + path)
                or "\\" in base + path):
            raise ValueError
        origin, route = urllib.parse.urlsplit(base), urllib.parse.urlsplit(path)
        if any((
            origin.scheme != "http", origin.hostname != "127.0.0.1",
            origin.username is not None, origin.password is not None,
            origin.port is None or not 1 <= origin.port <= 65535,
            origin.path, origin.query, origin.fragment,
            not path.startswith("/"), path.startswith("//"),
            route.scheme, route.netloc, route.fragment,
        )):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError(
            "Recording requests require an explicit IPv4 loopback HTTP origin and local path"
        ) from None
    return base + path


class NoRecordingRedirects(urllib.request.HTTPRedirectHandler):
    """Never forward recorder authorization or request bodies to a redirect target."""

    # The standard-library redirect callback requires this exact signature.
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Walkthrough:  # pylint: disable=too-many-instance-attributes
    """One actual application, one isolated browser page and a verified run ledger."""

    def __init__(self, output, *, fast=False, narrate=True):
        self.output = output
        self.fast = fast
        self.narrate = narrate and not fast
        self.roles = {
            role: secrets.token_urlsafe(32)
            for role in (
                "facilitator",
                "soc_analyst",
                "identity_responder",
                "endpoint_responder",
                "cloud_responder",
                "simulated_user",
            )
        }
        self.chapters = []
        self.audio = []
        self.console_errors = []
        self.requests_failed = []
        self.page = None
        self.started = None
        self.ffmpeg = None
        self.base = None
        self.run_id = None
        self.playwright = None
        self.video = None
        self.confirmed_count = None
        self.health_id = None
        self.events_count = None

    def request(self, path, *, role="facilitator", payload=None):
        """Send one authorized local request without redirects or proxy forwarding."""
        request = urllib.request.Request(
            local_request_url(self.base, path),
            headers={
                "Authorization": "Bearer " + self.roles[role],
                "Content-Type": "application/json",
            },
            data=json.dumps(payload).encode() if payload is not None else None,
            method="POST" if payload is not None else "GET",
        )
        # No environment proxy and no redirect; only the validated local origin.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRecordingRedirects()
        )
        with opener.open(request, timeout=20) as response:
            return json.load(response)

    def control(self, command, payload=None):
        return self.request("/api/facilitator/" + command, payload=payload or {})

    def resume(self):
        state = self.request("/api/facilitator/state")["controller"]["state"]
        if state == "paused":
            self.control("resume")

    def pause(self):
        state = self.request("/api/facilitator/state")["controller"]["state"]
        if state == "running":
            self.control("pause")

    def advance(self, seconds):
        self.resume()
        self.control("advance", {"elapsed_seconds": seconds})
        self.pause()

    def goto(self, path, role=None):
        from playwright.sync_api import expect  # pylint: disable=import-outside-toplevel

        if self.page.url.startswith(self.base):
            self.page.evaluate("() => sessionStorage.removeItem('netstrike.portal.token')")
        self.page.goto(self.base + path, wait_until="networkidle")
        if role:
            self.page.locator("#token-input").fill(self.roles[role])
            self.page.locator("#connect").click()
            expect(self.page.locator("#run-state")).not_to_have_text("disconnected")
        self.page.wait_for_timeout(250)

    def evidence(self, category="all", *, role="soc_analyst", query=""):
        self.goto("/evidence", role)
        self.page.locator("#category").select_option(category)
        self.page.locator("#search").fill(query)
        self.page.locator(".evidence-workspace").scroll_into_view_if_needed()
        self.page.wait_for_timeout(300)

    def participant_action(self, action_id, target_id):
        button = self.page.locator(f'button[data-action="{action_id}"]')
        button.locator("..").locator("input").fill(target_id)
        self.resume()
        with self.page.expect_response(
            lambda response: response.url.endswith("/api/participant/actions")
        ) as pending:
            button.click()
        assert pending.value.status == 200, "participant action request failed"
        result = pending.value.json()
        assert result["successful"] and result["status"] == "executed", result.get("message")
        self.pause()
        self.page.wait_for_timeout(400)

    def scene(self, index, operation):
        title, narration = SCENES[index]
        start = time.monotonic() - self.started
        operation()
        self.page.wait_for_timeout(400)
        self.page.screenshot(path=str(self.output / "frames" / f"{index + 1:02}.png"))
        duration = max(18, self.audio[index]["duration"] + 2) if not self.fast else 0.6
        remaining = duration - (time.monotonic() - self.started - start)
        if remaining > 0:
            self.page.wait_for_timeout(remaining * 1000)
        end = time.monotonic() - self.started
        self.chapters.append({"title": title, "start": start, "end": end, "narration": narration})
        print(f"{index + 1:02}/{len(SCENES)} {title}", flush=True)

    def prepare_audio(self):
        for index, (_title, narration) in enumerate(SCENES):
            text_path = self.output / "narration" / f"{index + 1:02}.txt"
            text_path.write_text(narration + "\n", encoding="utf-8")
            duration = 0
            path = None
            if self.narrate:
                if not shutil.which("say"):
                    raise RuntimeError(
                        "offline narration requires macOS say; use --no-narration elsewhere"
                    )
                source = self.output / "narration" / f"{index + 1:02}.aiff"
                path = source.with_suffix(".wav")
                checked(
                    ["say", "-v", "Samantha", "-r", "165", "-f", str(text_path), "-o", str(source)]
                )
                checked(
                    [
                        self.ffmpeg,
                        "-v",
                        "error",
                        "-n",
                        "-i",
                        str(source),
                        "-ar",
                        "48000",
                        "-ac",
                        "1",
                        "-c:a",
                        "pcm_s16le",
                        str(path),
                    ]
                )
                with wave.open(str(path)) as audio:
                    duration = audio.getnframes() / audio.getframerate()
            self.audio.append({"path": path, "duration": duration})

    # Optional recording libraries stay lazy so preview requires no extra packages.
    # pylint: disable=too-many-locals,import-outside-toplevel,consider-using-with
    def record(self):
        from playwright.sync_api import sync_playwright  # recording-only dependency
        import imageio_ffmpeg  # recording-only dependency

        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        for name in ("frames", "raw", "narration"):
            (self.output / name).mkdir()
        self.prepare_audio()
        with tempfile.TemporaryDirectory(prefix="netstrike-recording-") as temporary:
            task = Path(temporary)
            decoys = task / "decoys"
            decoys.mkdir()
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            self.base = f"http://127.0.0.1:{port}"
            self.run_id = "ui-walkthrough-" + secrets.token_hex(6)
            environment = dict(os.environ)
            environment.update(
                {
                    "NETSTRIKE_PORTAL_TOKENS": json.dumps(
                        {
                            token: {
                                "actor_id": "demo-" + role,
                                "role": role,
                            }
                            for role, token in self.roles.items()
                        }
                    ),
                    "NETSTRIKE_IDENTITY_AUDIT_KEY": secrets.token_urlsafe(48),
                    "NETSTRIKE_SSO_ALLOWED_ORIGINS": json.dumps([self.base]),
                    "NETSTRIKE_PORTAL_DATABASE": str(task / "portal.sqlite3"),
                    "NETSTRIKE_IMPACT_ROOT": str(decoys),
                    "NETSTRIKE_RUN_ID": self.run_id,
                    "NETSTRIKE_SCENARIO_PATH": str(
                        ROOT / "orchestrator/scenarios/full-play.v1.json"
                    ),
                }
            )
            with (self.output / "server.log").open("w", encoding="utf-8") as log:
                server = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "dashboard.app:create_default_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--log-level",
                        "warning",
                    ],
                    cwd=ROOT,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                try:
                    for _ in range(100):
                        if server.poll() is not None:
                            raise RuntimeError("local recording server failed; see server.log")
                        try:
                            self.request("/health")
                            break
                        except (urllib.error.URLError, ConnectionError):
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("local recording server readiness timed out")
                    with sync_playwright() as playwright:
                        self.playwright = playwright
                        browser = playwright.chromium.launch(channel="chrome", headless=True)
                        context = browser.new_context(
                            viewport={"width": 1600, "height": 820},
                            record_video_dir=str(self.output / "raw"),
                            record_video_size={"width": 1600, "height": 820},
                            accept_downloads=True,
                        )
                        self.page = context.new_page()
                        self.page.on(
                            "pageerror", lambda error: self.console_errors.append(str(error))
                        )
                        self.page.on(
                            "response",
                            lambda response: (
                                self.requests_failed.append(
                                    {
                                        "path": response.url.split(self.base)[-1],
                                        "status": response.status,
                                    }
                                )
                                if response.url.startswith(self.base) and response.status >= 400
                                else None
                            ),
                        )
                        self.started = time.monotonic()
                        self.perform()
                        video = self.page.video
                        context.close()
                        self.video = video.path()
                        browser.close()
                finally:
                    server.terminate()
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
        assert not self.console_errors, self.console_errors
        assert not self.requests_failed, self.requests_failed
        self.assemble()

    # Keep the reviewed chronological journey together for deterministic replay.
    # pylint: disable=too-many-locals,too-many-statements
    def perform(self):
        self.scene(0, lambda: self.goto("/facilitator", "facilitator"))

        def prepare():
            with self.page.expect_response(
                lambda response: response.url.endswith("/api/facilitator/prepare")
            ) as pending:
                self.page.locator('[data-command="prepare"]').click()
            assert pending.value.status == 200
            self.page.locator("#profile-summary").scroll_into_view_if_needed()

        self.scene(1, prepare)

        def first_mfa():
            self.control("start")
            self.advance(30)
            self.goto("/sso")
            self.page.locator("#view-mfa").wait_for(state="visible")

        self.scene(2, first_mfa)

        def deny():
            self.page.locator("#mfa-access-token").fill(self.roles["simulated_user"])
            self.resume()
            self.page.reload(wait_until="networkidle")
            self.page.locator("#mfa-access-token").fill(self.roles["simulated_user"])
            with self.page.expect_response(
                lambda response: response.url.endswith("/api/sso/scheduled-mfa")
            ) as pending:
                self.page.locator("#deny-mfa").click()
            assert pending.value.status == 200
            self.pause()
            self.page.locator("#scheduled-result").wait_for(state="visible")

        self.scene(3, deny)

        def messages():
            self.advance(300)
            self.goto("/participant", "cloud_responder")
            assert self.page.locator("#injects .inject").count() == 2
            self.page.locator("#injects").scroll_into_view_if_needed()

        self.scene(4, messages)

        def replay():
            self.advance(600)
            self.evidence("all", query="FIN-WS01")
            assert (
                self.page.locator("#signals").inner_text().count("endpoint.remote_access.succeeded")
                >= 2
            )

        self.scene(5, replay)

        def triage():
            self.advance(1500)
            self.resume()
            self.control("deliver", {"item_id": "MSEL-03"})
            self.pause()
            self.goto("/participant", "soc_analyst")
            form = self.page.locator("#dp1-form")
            form.locator('[name="identity"]').fill("Sarah Mitchell (sarah)")
            form.locator('[name="classification"]').select_option(label="Likely account compromise")
            for index, (reference, source) in enumerate(
                [
                    ("HD-1042", "helpdesk"),
                    ("factor-red-01", "identity"),
                    ("sess-red-01", "identity"),
                ]
            ):
                form.locator('[name="reference"]').nth(index).fill(reference)
                form.locator('[name="source"]').nth(index).fill(source)
            self.resume()
            with self.page.expect_response(
                lambda response: response.url.endswith("/api/participant/checkpoints/dp1")
            ) as pending:
                form.locator('button[type="submit"]').click()
            assert pending.value.status == 200 and pending.value.json()["passed"]
            self.pause()
            form.scroll_into_view_if_needed()

        self.scene(6, triage)

        def endpoint():
            self.advance(3600)
            self.evidence("endpoint")
            assert (
                "designated persistence" in self.page.locator("#signals").inner_text().lower()
                or "persistence" in self.page.locator("#signals").inner_text().lower()
            )

        self.scene(7, endpoint)

        def preserve():
            self.goto("/participant", "endpoint_responder")
            self.participant_action("evidence.artifact.preserve", "FIN-WS01-discovery-bundle")
            self.evidence("response", role="endpoint_responder")
            assert "executed" in self.page.locator("#signals").inner_text()

        self.scene(8, preserve)

        def cloud_initial():
            self.resume()
            self.control("checkpoints/dp2")
            self.advance(4500)
            self.evidence("cloud")
            assert self.page.locator(".signal-card").count() > 0

        self.scene(9, cloud_initial)

        def bulk():
            self.advance(5700)
            self.resume()
            self.control("checkpoints/dp3")
            self.advance(6000)
            self.evidence("cloud")
            cloud = self.request("/api/participant/cloud", role="cloud_responder")
            self.confirmed_count = next(iter(cloud["state"]["exposure"].values()))[
                "confirmed_count"
            ]
            assert self.confirmed_count == 25
            assert "cloud.extortion.claimed" in self.page.locator("#signals").inner_text()

        self.scene(10, bulk)

        def contain_cloud():
            cloud = self.request("/api/participant/cloud", role="cloud_responder")
            bucket = next(iter(cloud["state"]["objects"].values()))["bucket_id"]
            key = next(iter(cloud["state"]["keys"]))
            self.goto("/participant", "cloud_responder")
            self.page.locator("#load-cloud").click()
            self.participant_action("cloud.evidence.preserve", bucket)
            self.participant_action("cloud.key.revoke", key)
            self.evidence("response", role="cloud_responder")

        self.scene(11, contain_cloud)

        def impact():
            self.advance(6600)
            self.resume()
            self.control("checkpoints/dp4")
            self.pause()
            recovery = self.request("/api/participant/recovery", role="cloud_responder")
            assert recovery["fixture"]["available_originals"] == 0
            assert recovery["fixture"]["originals_unchanged"]
            self.evidence("recovery")

        self.scene(12, impact)

        def preview():
            self.goto("/participant", "cloud_responder")
            self.page.locator("#load-recovery").click()
            self.page.locator('#recovery-actions [name="fixture_id"]').fill(
                "FILE01-disposable-fixture"
            )
            assert self.page.locator("#recovery-preview").is_checked()
            self.recovery_action("recovery.fixture.restore", expected="dry_run")
            assert (
                self.request("/api/participant/recovery", role="cloud_responder")["fixture"][
                    "available_originals"
                ]
                == 0
            )
            self.page.locator("#recovery-actions").scroll_into_view_if_needed()

        self.scene(13, preview)

        def restore():
            self.page.locator("#recovery-preview").uncheck()
            self.recovery_action("recovery.fixture.restore")
            self.recovery_action("recovery.health.validate")
            self.page.locator("#load-recovery").click()
            recovery = self.request("/api/participant/recovery", role="cloud_responder")
            assert recovery["fixture"]["available_originals"] == 5
            assert recovery["fixture"]["baseline_verified"]
            self.health_id = next(
                event["event_id"]
                for event in reversed(recovery["audit"])
                if event["event_type"] == "recovery.health.verified"
            )
            self.page.locator("#recovery-summary").scroll_into_view_if_needed()

        self.scene(14, restore)

        def brief():
            self.advance(6900)
            form = self.page.locator("#recovery-brief")
            for name, value in {
                "confirmed_scope": (
                    "Sarah's synthetic identity, FIN-WS01 and 25 mock customer records."
                ),
                "confirmed_cloud_records": str(self.confirmed_count),
                "business_impact": (
                    "Five disposable exercise files became unavailable; "
                    "no production files or encryption."
                ),
                "actions_taken": (
                    "Preserved evidence, revoked the mock key, restored five decoys "
                    "and verified hashes."
                ),
                "remaining_risk": (
                    "Mock access is confirmed. External transfer is not established. "
                    "Earlier identity persistence needs review."
                ),
                "recommendations": (
                    "Strengthen helpdesk callback verification.\n"
                    "Restrict service-key privilege and review endpoint persistence."
                ),
                "evidence_ids": self.health_id,
            }.items():
                form.locator(f'[name="{name}"]').fill(value)
            self.resume()
            with self.page.expect_response(
                lambda response: response.url.endswith("/api/participant/recovery/brief")
            ) as pending:
                form.locator('button[type="submit"]').click()
            assert pending.value.status == 200
            self.pause()
            form.scroll_into_view_if_needed()

        self.scene(15, brief)

        def finish():
            self.advance(7800)
            self.goto("/facilitator", "facilitator")
            state = self.request("/api/facilitator/state")
            assert state["controller"]["state"] == "completed"
            assert state["impact"]["final_review"]["passed"]
            with self.page.expect_download() as pending:
                self.page.locator("#download-jsonl").click()
            pending.value.save_as(self.output / "events.jsonl")
            self.validate_ledger()
            self.mobile_check()

        self.scene(16, finish)

        def reset():
            self.page.locator("#new-run-id").fill(self.run_id + "-fresh")
            with self.page.expect_response(
                lambda response: response.url.endswith("/api/facilitator/reset")
            ) as pending:
                self.page.locator("#reset").click()
            assert pending.value.status == 200
            self.page.wait_for_timeout(400)
            state = self.request("/api/facilitator/state")
            assert state["controller"]["state"] == "ready"
            assert state["controller"]["run_id"] != self.run_id
            recovery = self.request("/api/participant/recovery", role="cloud_responder")
            assert recovery["fixture"]["baseline_verified"]
            self.goto("/evidence", "soc_analyst")
            assert self.page.locator(".signal-card").count() == 0

        self.scene(17, reset)

    def recovery_action(self, action, expected="executed"):
        self.resume()
        with self.page.expect_response(
            lambda response: response.url.endswith("/api/participant/recovery/action")
        ) as pending:
            self.page.locator(f'[data-recovery="{action}"]').click()
        assert pending.value.status == 200
        assert pending.value.json()["status"] == expected
        self.pause()

    def validate_ledger(self):
        from shared.events import EventValidator  # pylint: disable=import-outside-toplevel

        events = [
            json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()
        ]
        validator = EventValidator()
        for event in events:
            validator.validate(event)
            assert event["run_id"] == self.run_id
        assert len({event["event_id"] for event in events}) == len(events)
        assert [event["sequence"] for event in events] == sorted(
            event["sequence"] for event in events
        )
        self.events_count = len(events)

    def mobile_check(self):
        # A separate browser process prevents a secondary mobile viewport from
        # changing the primary headless Chrome compositor's recorded surface.
        browser = self.playwright.chromium.launch(channel="chrome", headless=True)
        try:
            context = browser.new_context(viewport={"width": 390, "height": 844})
            page = context.new_page()
            page.goto(self.base + "/evidence", wait_until="networkidle")
            page.locator("#token-input").fill(self.roles["soc_analyst"])
            with page.expect_response(
                lambda response: "/api/participant/evidence" in response.url
            ):
                page.locator("#connect").click()
            page.locator(".signal-card").first.wait_for(state="visible")
            assert page.locator("html").evaluate("(node) => node.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(self.output / "frames" / "mobile-evidence.png"))
        finally:
            browser.close()

    # wave.open's write-mode return type is mis-inferred by the lint dependency.
    # pylint: disable=no-member
    def assemble(self):
        duration = self.chapters[-1]["end"] + 1
        manifest = {
            "run_id": self.run_id,
            "capture": "actual browser video; no mocked API responses",
            "synthetic_only": True,
            "splunk_connected": False,
            "events_validated": self.events_count,
            "play_completed": True,
            "decoys_restored": True,
            "application_reset_verified": True,
            "server_stopped": True,
            "browser_errors": self.console_errors,
            "failed_http_responses": self.requests_failed,
            "chapters": self.chapters,
        }
        manifest["source_git_revision"] = checked(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        ).stdout.strip()
        manifest["source_sha256"] = {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in (
                "dashboard/evidence.py",
                "dashboard/service.py",
                "dashboard/app.py",
                "dashboard/static/evidence.html",
                "dashboard/static/evidence.js",
                "dashboard/static/styles.css",
                "scripts/record_ui_walkthrough.py",
            )
        }
        (self.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        subtitles = []
        for index, chapter in enumerate(self.chapters):
            subtitles.append(
                f"{index + 1}\n{subtitle_time(chapter['start'])} --> "
                f"{subtitle_time(chapter['end'])}\n"
                f"{index + 1:02} / {len(self.chapters)} · {chapter['title']}\n"
                "Local synthetic exercise · Clock advanced for demonstration\n"
            )
        (self.output / "chapters.srt").write_text("\n".join(subtitles), encoding="utf-8")

        def ass_time(seconds):
            centiseconds = round(seconds * 100)
            hours, centiseconds = divmod(centiseconds, 360000)
            minutes, centiseconds = divmod(centiseconds, 6000)
            seconds, centiseconds = divmod(centiseconds, 100)
            return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"

        ass = [
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1600\nPlayResY: 900\n",
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
            "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n",
            "Style: Caption,Arial,24,&H00FFFFFF,&H00FFFFFF,&H001F1107,&H001F1107,"
            "0,0,0,0,100,100,0,0,1,1,0,2,20,20,12,1\n",
            "[Events]\nFormat: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text\n",
        ]
        for index, chapter in enumerate(self.chapters):
            title = f"{index + 1:02} / {len(self.chapters)} · {chapter['title']}"
            ass.append(
                f"Dialogue: 0,{ass_time(chapter['start'])},{ass_time(chapter['end'])},"
                f"Caption,,0,0,0,,{title}\\N{{\\fs17}}"
                "Local synthetic exercise · Clock advanced for demonstration\n"
            )
        (self.output / "chapters.ass").write_text("".join(ass), encoding="utf-8")
        inputs = [self.ffmpeg, "-v", "error", "-n", "-i", str(self.video)]
        if self.narrate:
            samples = bytearray(round(duration * 48000) * 2)
            for chapter, audio in zip(self.chapters, self.audio):
                with wave.open(str(audio["path"])) as source:
                    clip = source.readframes(source.getnframes())
                offset = round(chapter["start"] * 48000) * 2
                samples[offset : offset + len(clip)] = clip
            audio_path = self.output / "narration.wav"
            with wave.open(str(audio_path), "wb") as target:
                target.setnchannels(1)
                target.setsampwidth(2)
                target.setframerate(48000)
                target.writeframes(samples)
            inputs.extend(["-i", str(audio_path)])
        # Reserve a caption strip below the actual 1600x820 browser viewport.
        filters = "pad=1600:900:0:0:color=0x07111f,subtitles=chapters.ass"
        inputs.extend(
            [
                "-vf",
                filters,
                "-t",
                str(duration),
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
            ]
        )
        if self.narrate:
            inputs.extend(["-c:a", "aac", "-b:a", "160k"])
        inputs.append(str(self.output / "Operation-Silent-Spider-UI-Walkthrough.mp4"))
        checked(inputs, cwd=self.output)
        print(
            json.dumps(
                {
                    "video": str(self.output / "Operation-Silent-Spider-UI-Walkthrough.mp4"),
                    "seconds": round(duration, 1),
                    "events": self.events_count,
                }
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute", action="store_true", help="Run a disposable scenario and record actual UI"
    )
    parser.add_argument(
        "--output", type=Path, help="New output directory; existing files are never overwritten"
    )
    parser.add_argument(
        "--fast", action="store_true", help="Short silent browser smoke-check recording"
    )
    parser.add_argument("--no-narration", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "preview_only": True,
                    "writes_performed": False,
                    "chapters": [title for title, _ in SCENES],
                }
            )
        )
        return
    if args.output is None:
        parser.error("--execute requires a new --output directory")
    output = args.output.resolve()
    if output.exists():
        parser.error("output directory must not already exist")
    output.mkdir(parents=True)
    Walkthrough(output, fast=args.fast, narrate=not args.no_narration).record()


if __name__ == "__main__":
    main()
