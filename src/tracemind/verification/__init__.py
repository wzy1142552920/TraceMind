"""Read-only verification backends for database-state evidence."""

from tracemind.verification.backend import (
    ReadOnlyVerificationBackend,
    TableDescription,
    VerificationDataError,
    VerificationRowResult,
    VerificationTargetError,
)
from tracemind.verification.fake import (
    FakeVerificationBackend,
    load_verification_data,
)

__all__ = [
    "FakeVerificationBackend",
    "ReadOnlyVerificationBackend",
    "TableDescription",
    "VerificationDataError",
    "VerificationRowResult",
    "VerificationTargetError",
    "load_verification_data",
]
