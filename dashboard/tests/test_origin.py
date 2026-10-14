"""Exact SSO origin allowlist tests."""

from __future__ import annotations

import pytest

from dashboard.origin import (
    OriginAllowlist,
    OriginConfigurationError,
    normalize_origin,
)


def test_origin_normalization_is_exact_and_case_insensitive_for_authority() -> None:
    assert normalize_origin("HTTPS://CTRL01.CITEF.TEST:8443/") == (
        "https://ctrl01.citef.test:8443"
    )


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*",
        "file:///tmp/sso",
        "https://user:secret@ctrl01.citef.test",
        "https://ctrl01.citef.test/sso",
        "https://ctrl01.citef.test?next=external",
        "https://ctrl01.citef.test:invalid",
    ],
)
def test_unsafe_origin_configuration_is_rejected(origin) -> None:
    with pytest.raises(OriginConfigurationError):
        normalize_origin(origin)


def test_origin_allowlist_cannot_be_empty() -> None:
    with pytest.raises(OriginConfigurationError, match="at least one"):
        OriginAllowlist([])
