"""The sole write path for evidence collected during a diagnosis run."""

from __future__ import annotations

import json

from tracemind.diagnosis.evidence import Evidence, EvidenceKind


class InvalidBindingError(ValueError):
    """Raised when evidence is bound to a conflicting target."""

    code = "INVALID_BINDING"


class EvidenceLedger:
    """Ordered, deduplicating evidence store owned by the runtime."""

    def __init__(self, max_content_bytes: int = 32768) -> None:
        self._max_content_bytes = max_content_bytes
        self._items: list[Evidence] = []
        self._by_key: dict[str, Evidence] = {}

    def add(self, evidence: Evidence) -> Evidence:
        """Add evidence once per (kind, source_ref), returning the stored item."""
        key = self.dedupe_key(evidence.kind, evidence.source_ref)
        existing = self._by_key.get(key)
        if existing is not None:
            return existing

        self._compact_content(evidence)
        self._items.append(evidence)
        self._by_key[key] = evidence
        return evidence

    def get(self, evidence_id: str) -> Evidence | None:
        """Look up evidence by its runtime ID."""
        return next(
            (item for item in self._items if item.evidence_id == evidence_id),
            None,
        )

    def all(self) -> list[Evidence]:
        """Return evidence in insertion order."""
        return list(self._items)

    def by_source_ref(self, source_ref: str) -> list[Evidence]:
        """Return all evidence whose source reference matches exactly."""
        return [
            item for item in self._items if item.source_ref == source_ref
        ]

    def by_requirement(
        self,
        hypothesis_id: str,
        requirement_id: str,
    ) -> list[Evidence]:
        """Return evidence obtained for one hypothesis requirement."""
        return [
            item
            for item in self._items
            if item.has_binding(hypothesis_id, requirement_id)
        ]

    def bind(
        self,
        evidence_id: str,
        hypothesis_id: str,
        requirement_id: str,
        tool_call_id: str | None = None,
    ) -> Evidence:
        """Bind evidence to a requirement; one fact may serve several hypotheses."""
        evidence = self.get(evidence_id)
        if evidence is None:
            raise InvalidBindingError(f"evidence does not exist: {evidence_id}")
        if not hypothesis_id or not requirement_id:
            raise InvalidBindingError(
                "hypothesis_id and requirement_id must be provided together"
            )

        evidence.add_binding(hypothesis_id, requirement_id, tool_call_id)
        if evidence.bound_hypothesis_id is None:
            evidence.bound_hypothesis_id = hypothesis_id
            evidence.bound_requirement_id = requirement_id
        if (
            evidence.bound_hypothesis_id == hypothesis_id
            and evidence.bound_requirement_id == requirement_id
            and evidence.tool_call_id is None
        ):
            evidence.tool_call_id = tool_call_id
        return evidence

    def dedupe_key(self, kind: EvidenceKind, source_ref: str) -> str:
        """Return the stable identity used to deduplicate evidence."""
        return f"{kind}:{source_ref}"

    def __len__(self) -> int:
        return len(self._items)

    def _compact_content(self, evidence: Evidence) -> None:
        if not evidence.content:
            return
        raw = json.dumps(
            evidence.content,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        if len(raw) <= self._max_content_bytes:
            return
        preview = raw[: self._max_content_bytes].decode(
            "utf-8",
            errors="ignore",
        )
        evidence.content = {
            "truncated": True,
            "original_bytes": len(raw),
            "preview": preview,
        }
