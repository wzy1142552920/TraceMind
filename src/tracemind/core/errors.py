"""Domain errors for TraceMind."""

from __future__ import annotations


class TraceMindError(Exception):
    """Base class for TraceMind errors."""


class LogParseError(TraceMindError):
    """Raised when a log file cannot be parsed fatally."""
