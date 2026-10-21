"""TraceMind: local-first, evidence-driven Java incident localization agent."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tracemind")
except PackageNotFoundError:
    __version__ = "0.2.0"

__all__ = ["__version__"]
