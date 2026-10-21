"""Domain errors for TraceMind."""

from __future__ import annotations


class TraceMindError(Exception):
    """Base class for TraceMind errors."""


class LogParseError(TraceMindError):
    """Raised when a log file cannot be parsed fatally."""


class JavaIndexError(TraceMindError):
    """Raised when a Java repository cannot be indexed or queried."""


class LLMConfigError(TraceMindError):
    """Raised when LLM configuration or credentials are invalid."""
