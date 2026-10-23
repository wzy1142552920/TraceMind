"""Immutable models for user-provided JVM snapshot bundles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ARTIFACT_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,31}$"
MAX_ARTIFACTS = 8
MAX_SERVICE_LENGTH = 128


class ArtifactKind(StrEnum):
    """Supported text snapshot kinds."""

    THREAD_DUMP = "thread_dump"
    THREAD_CPU = "thread_cpu"
    GC_LOG = "gc_log"
    HEAP_HISTOGRAM = "heap_histogram"


class ArtifactError(ValueError):
    """The artifact bundle is missing, malformed, unsafe, or out of bounds."""


class ArtifactSpec(BaseModel):
    """One text artifact declared by the manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=ARTIFACT_ID_PATTERN)
    kind: ArtifactKind
    path: str = Field(min_length=1, max_length=256)


class ArtifactManifest(BaseModel):
    """Strict manifest for a bundle of user-provided JVM snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"]
    service: str = Field(min_length=1, max_length=MAX_SERVICE_LENGTH)
    instance: str | None = Field(default=None, min_length=1, max_length=128)
    captured_at: str | None = Field(default=None, max_length=64)
    artifacts: tuple[ArtifactSpec, ...] = Field(
        min_length=1,
        max_length=MAX_ARTIFACTS,
    )

    @field_validator("captured_at")
    @classmethod
    def _validate_captured_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("must be an ISO-8601 timestamp") from exc
        return value


@dataclass(frozen=True)
class ArtifactDocument:
    """One validated artifact with its decoded, immutable text lines."""

    spec: ArtifactSpec
    source_name: str
    lines: tuple[str, ...]
    byte_size: int
    line_count: int
    warnings: tuple[str, ...] = ()

    @property
    def artifact_id(self) -> str:
        return self.spec.id

    @property
    def kind(self) -> ArtifactKind:
        return self.spec.kind


class ArtifactRecord(BaseModel):
    """Non-sensitive artifact metadata exposed to reports and run artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    kind: ArtifactKind
    source_name: str
    source_environment: Literal["user_provided"] = "user_provided"
    line_count: int = Field(ge=1)
    byte_size: int = Field(ge=1)
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ArtifactBundle:
    """A fully validated, read-only collection of JVM snapshots."""

    root: Path
    manifest: ArtifactManifest
    documents: tuple[ArtifactDocument, ...]
    records: tuple[ArtifactRecord, ...]

    def by_kind(self, kind: ArtifactKind) -> tuple[ArtifactDocument, ...]:
        """Return documents of one kind in manifest order."""
        return tuple(doc for doc in self.documents if doc.kind is kind)

    def document(self, artifact_id: str) -> ArtifactDocument | None:
        """Return a document by manifest id, or None when it is unknown."""
        for document in self.documents:
            if document.artifact_id == artifact_id:
                return document
        return None

    def has_kind(self, kind: ArtifactKind) -> bool:
        """Whether at least one artifact of the requested kind was loaded."""
        return any(doc.kind is kind for doc in self.documents)
