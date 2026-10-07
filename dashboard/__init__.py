"""Participant and facilitator API for Operation Silent Spider."""

# Public names are supplied lazily by PEP 562, not undefined runtime exports.
__all__ = ["create_app", "create_default_app"]  # pylint: disable=undefined-all-variable


def __getattr__(name):
    """Keep offline preflight importable even when portal dependencies are absent."""
    if name not in __all__:
        raise AttributeError(name)
    from . import app  # pylint: disable=import-outside-toplevel
    return getattr(app, name)
