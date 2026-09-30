"""Exact-origin allowlisting for the isolated SSO browser surface."""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit

from fastapi import Request


class OriginConfigurationError(ValueError):
    """Raised when a configured CITEF origin is not an exact HTTP origin."""


class OriginDeniedError(PermissionError):
    """Raised when a request does not originate from an allowlisted service."""


def normalize_origin(value: str) -> str:
    """Return a canonical scheme/authority pair or reject the value."""

    if not isinstance(value, str) or not value.strip():
        raise OriginConfigurationError("SSO origins must be non-empty strings")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OriginConfigurationError("SSO origins must use http or https")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise OriginConfigurationError("SSO origin port is invalid") from exc
    if not parsed.hostname or "*" in parsed.netloc:
        raise OriginConfigurationError("SSO origins cannot use wildcards")
    if parsed.username or parsed.password:
        raise OriginConfigurationError("SSO origins cannot contain user information")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise OriginConfigurationError("SSO origins cannot contain paths or queries")
    authority = parsed.hostname.lower()
    if ":" in authority and not authority.startswith("["):
        authority = f"[{authority}]"
    if parsed_port is not None:
        authority = f"{authority}:{parsed_port}"
    return f"{parsed.scheme.lower()}://{authority}"


class OriginAllowlist:  # pylint: disable=too-few-public-methods
    """Validate browser Origin and navigation Host against an exact allowlist."""

    def __init__(self, origins: Iterable[str]) -> None:
        self.origins = frozenset(normalize_origin(origin) for origin in origins)
        if not self.origins:
            raise OriginConfigurationError(
                "at least one NETSTRIKE_SSO_ALLOWED_ORIGINS value is required"
            )

    def authorize(self, request: Request) -> str:
        """Return the accepted origin without falling back to wildcard matching."""

        supplied = request.headers.get("origin")
        try:
            if supplied:
                origin = normalize_origin(supplied)
            else:
                origin = normalize_origin(
                    f"{request.url.scheme}://{request.headers.get('host', '')}"
                )
        except OriginConfigurationError as exc:
            raise OriginDeniedError("request origin is not allowed") from exc
        if origin not in self.origins:
            raise OriginDeniedError("request origin is not allowed")
        return origin
