"""Contained SSO state, safety-boundary, and reset tests."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from dashboard.sso import (
    SsoBoundaryError,
    SsoExperience,
    SsoExperienceConfig,
    SsoExperienceError,
)


SCENARIO_PATH = (
    Path(__file__).resolve().parents[2]
    / "orchestrator"
    / "scenarios"
    / "identity-slice.v1.json"
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 30, 20, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


class AuditProbe:
    def __init__(self) -> None:
        self.actions = []
        self.results = []
        self.identities = []
        self.credential_submissions = 0

    def __call__(self, payload):
        self.actions.append(payload["action"])
        self.results.append(payload["result"])
        self.identities.append(payload["synthetic_identity"])
        self.credential_submissions += "synthetic_credential" in payload
        return {"event_id": payload["source_event_id"]}


def _raw_config():
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    return deepcopy(scenario["participant_experience"]["sso"])


def _state():
    return SimpleNamespace(
        identities={
            "sarah": {
                "display_name": "Sarah Mitchell",
                "enabled": True,
                "synthetic": True,
            }
        },
        sessions={
            "sess-red-01": {"identity_id": "sarah", "active": True},
            "sess-sarah-01": {"identity_id": "sarah", "active": True},
        },
        mfa={"sarah": {"push_count": 0, "decision": "pending"}},
    )


def _experience(raw=None):
    state = _state()
    clock = Clock()
    audit = AuditProbe()
    experience = SsoExperience(
        SsoExperienceConfig.from_mapping(raw or _raw_config()),
        identity_state=lambda: state,
        audit_sink=audit,
        clock=clock,
    )
    return experience, state, audit, clock


def test_scenario_configuration_uses_reserved_synthetic_domain() -> None:
    config = SsoExperienceConfig.from_mapping(_raw_config())

    assert config.username == "sarah@simcorp.test"
    assert config.service_name == "SimCorp Access"
    assert config.suspicious_sessions[0].session_id == "sess-red-01"

    invalid = _raw_config()
    invalid["identity"]["username"] = "sarah@simcorp.com"
    with pytest.raises(SsoExperienceError, match="reserved .test domain"):
        SsoExperienceConfig.from_mapping(invalid)


def test_external_account_is_rejected_without_forwarding_its_credential() -> None:
    experience, _state_value, audit, _clock = _experience()

    with pytest.raises(SsoBoundaryError, match="outside"):
        experience.sign_in("person@external.example", "unknown-real-value")

    assert audit.actions == ["identity.sign_in.rejected"]
    assert audit.identities == ["external-account"]
    assert audit.credential_submissions == 0


def test_account_disable_cannot_be_bypassed_by_pending_local_mfa():
    experience, state, audit, _clock = _experience()
    experience.sign_in("sarah@simcorp.test", "exercise-first")
    challenge = experience.sign_in("sarah@simcorp.test", "exercise-second")
    state.identities["sarah"]["enabled"] = False
    with pytest.raises(SsoExperienceError, match="disabled"):
        experience.decide_mfa(challenge["challenge"]["id"], "approve")
    assert experience.state()["view"] == "locked"
    assert "sess-sso-current" not in state.sessions
    assert audit.actions[-1] == "identity.mfa.challenge.cancelled"


def test_unicode_and_non_string_decisions_fail_cleanly():
    experience, _state_value, _audit, _clock = _experience()
    with pytest.raises(SsoBoundaryError):
        experience.sign_in("é@external.example", "unused")
    with pytest.raises(SsoExperienceError):
        experience.decide_mfa("any", [])


def test_failure_mfa_success_and_suspicious_session_views_are_reachable() -> None:
    experience, state, audit, _clock = _experience()

    failed = experience.sign_in("sarah@simcorp.test", "first-exercise-value")
    challenge = experience.sign_in("sarah@simcorp.test", "second-exercise-value")
    approved = experience.decide_mfa(
        challenge["challenge"]["id"], "approve"
    )
    sessions = experience.review_sessions()

    assert failed["view"] == "failure"
    assert challenge["view"] == "mfa"
    assert approved["view"] == "success"
    assert sessions["view"] == "suspicious_session"
    assert sessions["sessions"][0]["id"] == "sess-red-01"
    assert state.sessions["sess-sso-current"]["active"] is True
    assert state.mfa["sarah"] == {"push_count": 1, "decision": "approved"}
    assert audit.credential_submissions == 2
    experience.reset()
    assert "sess-sso-current" not in state.sessions
    assert state.mfa["sarah"] == {"push_count": 0, "decision": "pending"}
    assert experience.baseline_mismatches() == ()


def test_configured_failures_can_reach_lockout_without_real_authentication() -> None:
    raw = _raw_config()
    raw["initial_failures_before_mfa"] = 2
    raw["lockout_threshold"] = 2
    experience, _state_value, audit, _clock = _experience(raw)

    first = experience.sign_in("sarah@simcorp.test", "exercise-value-one")
    second = experience.sign_in("sarah@simcorp.test", "exercise-value-two")

    assert first["view"] == "failure"
    assert second["view"] == "locked"
    assert audit.results == ["failure", "blocked"]


def test_expired_challenge_is_denied_and_reset_clears_generated_state() -> None:
    experience, state, audit, clock = _experience()
    experience.sign_in("sarah@simcorp.test", "exercise-value-one")
    challenge = experience.sign_in("sarah@simcorp.test", "exercise-value-two")
    clock.advance(31)

    expired = experience.decide_mfa(challenge["challenge"]["id"], "approve")

    assert expired["view"] == "failure"
    assert audit.actions[-1] == "identity.mfa.challenge.expired"
    experience.reset()
    assert experience.state()["view"] == "sign_in"
    assert experience.baseline_mismatches() == ()
    assert "sess-sso-current" not in state.sessions
    assert state.mfa["sarah"] == {"push_count": 0, "decision": "pending"}
