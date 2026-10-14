"""Portal authentication and authorization tests."""

from __future__ import annotations

import pytest

from dashboard.auth import (
    PortalAuthenticationError,
    PortalAuthorizationError,
    PortalPrincipal,
    TokenAuthenticator,
)


TOKEN = "participant-token-at-least-24-characters"


def test_authenticator_resolves_server_owned_principal() -> None:
    authenticator = TokenAuthenticator(
        {TOKEN: PortalPrincipal("learner-01", "identity_responder")}
    )

    principal = authenticator.authenticate(
        f"Bearer {TOKEN}", allowed_roles=frozenset({"identity_responder"})
    )

    assert principal == PortalPrincipal("learner-01", "identity_responder")


@pytest.mark.parametrize("authorization", [None, "Basic value", "Bearer wrong"])
def test_missing_or_invalid_credentials_fail_closed(authorization) -> None:
    authenticator = TokenAuthenticator(
        {TOKEN: PortalPrincipal("learner-01", "identity_responder")}
    )

    with pytest.raises(PortalAuthenticationError):
        authenticator.authenticate(
            authorization, allowed_roles=frozenset({"identity_responder"})
        )


def test_endpoint_role_is_enforced_after_authentication() -> None:
    authenticator = TokenAuthenticator(
        {TOKEN: PortalPrincipal("learner-01", "identity_responder")}
    )

    with pytest.raises(PortalAuthorizationError):
        authenticator.authenticate(
            f"Bearer {TOKEN}", allowed_roles=frozenset({"facilitator"})
        )


def test_short_or_empty_configuration_is_rejected() -> None:
    with pytest.raises(ValueError):
        TokenAuthenticator({})
    with pytest.raises(ValueError, match="24"):
        TokenAuthenticator(
            {"too-short": PortalPrincipal("learner-01", "identity_responder")}
        )
