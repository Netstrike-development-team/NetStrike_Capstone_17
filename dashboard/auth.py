"""Server-owned bearer-token authentication for the isolated exercise portal."""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from typing import Mapping


class PortalAuthenticationError(PermissionError):
    """Raised when a portal credential is absent or invalid."""


class PortalAuthorizationError(PermissionError):
    """Raised when an authenticated principal lacks the required role."""


@dataclass(frozen=True)
class PortalPrincipal:
    """Identity and role resolved from server-side token configuration."""

    actor_id: str
    role: str


class TokenAuthenticator:
    """Authenticate opaque tokens without exposing configured token values."""

    def __init__(self, principals: Mapping[str, PortalPrincipal]) -> None:
        if not principals:
            raise ValueError("at least one portal token must be configured")
        for token, principal in principals.items():
            if not isinstance(token, str) or len(token) < 24:
                raise ValueError("portal tokens must contain at least 24 characters")
            if not principal.actor_id.strip() or not principal.role.strip():
                raise ValueError("portal principals require actor_id and role")
        self._principals = dict(principals)

    @classmethod
    def from_json(cls, raw: str) -> "TokenAuthenticator":
        """Load token mappings from injected JSON configuration."""

        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("portal token configuration must be a JSON object")
        principals = {}
        for token, record in parsed.items():
            if not isinstance(record, dict) or set(record) != {"actor_id", "role"}:
                raise ValueError("each token must map to actor_id and role")
            principals[str(token)] = PortalPrincipal(
                actor_id=str(record["actor_id"]), role=str(record["role"])
            )
        return cls(principals)

    @classmethod
    def from_environment(cls) -> "TokenAuthenticator":
        """Load configuration without providing unsafe development defaults."""

        raw = os.getenv("NETSTRIKE_PORTAL_TOKENS")
        if not raw:
            raise ValueError("NETSTRIKE_PORTAL_TOKENS must be configured")
        return cls.from_json(raw)

    def authenticate(
        self,
        authorization: str | None,
        *,
        allowed_roles: frozenset[str],
    ) -> PortalPrincipal:
        """Resolve one bearer token and enforce an endpoint role allowlist."""

        if not authorization or not authorization.startswith("Bearer "):
            raise PortalAuthenticationError("Bearer authentication is required")
        supplied = authorization.removeprefix("Bearer ")
        principal = None
        for token, candidate in self._principals.items():
            if hmac.compare_digest(supplied, token):
                principal = candidate
        if principal is None:
            raise PortalAuthenticationError("invalid bearer credential")
        if principal.role not in allowed_roles:
            raise PortalAuthorizationError("role is not authorized for this endpoint")
        return principal
