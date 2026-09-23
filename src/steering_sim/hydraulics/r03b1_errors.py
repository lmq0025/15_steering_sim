"""Explicit failures for AMESim mechanisms that are not yet traceably closed."""


class UnresolvedAmesimUtilityError(RuntimeError):
    """Raised instead of silently substituting an unverified textbook equation."""

