"""Shared contracts used across NetStrike services and modules."""

from .events import (
    CURRENT_SCHEMA_VERSION,
    EventBuilder,
    EventCompatibilityError,
    EventContext,
    EventContractError,
    EventLedger,
    EventLedgerError,
    EventValidationError,
    EventValidator,
    correlation_key,
    entity,
    redact_sensitive,
    safety_marker,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "EventBuilder",
    "EventCompatibilityError",
    "EventContext",
    "EventContractError",
    "EventLedger",
    "EventLedgerError",
    "EventValidationError",
    "EventValidator",
    "correlation_key",
    "entity",
    "redact_sensitive",
    "safety_marker",
]
