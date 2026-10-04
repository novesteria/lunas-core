"""Dataclasses for validator output: ``LayerResult`` and ``ValidationReport``.

These are the contract between the pipeline and any consumer. Stable in
the public API — changes here are semver-breaking from v1.0.0 onward.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class LayerKind(StrEnum):
    """Categorizes a check layer by how it judges.

    ``deterministic`` layers (19 of 21) run AST parsing, regex, file I/O,
    or subprocess commands. No LLM call. Reproducible without API keys.

    ``hybrid`` layers (2 of 21: design_fidelity, feature_coverage) ask an
    LLM for judgment but reserve a deterministic evidence check that can
    override the LLM verdict. The deterministic check has the final word.

    ``llm_judge`` is reserved for layers that would rely on the LLM alone.
    No shipped layer uses it.
    """
    deterministic = "deterministic"
    llm_judge = "llm_judge"
    hybrid = "hybrid"


class Verdict(StrEnum):
    """The outcome of a single check layer."""
    passed = "passed"
    failed = "failed"
    skipped = "skipped"  # e.g. a Python layer on a Node-only project
    error = "error"      # the layer itself crashed; treat as failed


@dataclass(frozen=True)
class LayerResult:
    """One layer's output."""

    name: str
    """Stable identifier (e.g. ``build_install``, ``ast_python_imports``).
    Used in expected.json fixtures and bench result diffs."""

    kind: LayerKind
    """Whether this layer is deterministic, LLM-judge, or hybrid."""

    verdict: Verdict
    """Pass / fail / skip / error."""

    duration_seconds: float
    """Wall-clock duration of this layer. For bench reproducibility."""

    summary: str
    """One-line human-readable explanation of the result."""

    details: dict[str, Any] = field(default_factory=dict)
    """Structured failure context: line numbers, missing symbols, stderr
    excerpts. Keys are layer-specific but documented per layer."""

    override_fired: bool = False
    """For hybrid layers only: True if the deterministic override changed
    the verdict away from the LLM's preferred answer."""

    def passed(self) -> bool:
        """True when this layer reports pass."""
        return self.verdict == Verdict.passed


@dataclass(frozen=True)
class ValidationReport:
    """The full output of a pipeline run."""

    passed: bool
    """Overall verdict: True if every non-skipped layer passed."""

    layers: list[LayerResult]
    """All layer results in the order they ran."""

    stacks_detected: list[str]
    """Stacks the pipeline detected in the input (e.g. ``["python", "node"]``)."""

    code_path: str
    """The directory that was validated."""

    duration_seconds: float
    """Total wall-clock duration."""

    timestamp: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    """ISO-8601 UTC timestamp when the run started."""

    lunas_version: str = ""
    """The Lunas version that produced this report. Populated by the
    pipeline so bench results trace back to a specific release."""

    # ----------------------------------------------------------------- exporters

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict."""
        return {
            "passed": self.passed,
            "stacks_detected": self.stacks_detected,
            "code_path": self.code_path,
            "duration_seconds": self.duration_seconds,
            "timestamp": self.timestamp,
            "lunas_version": self.lunas_version,
            # the pre-rename key, kept for one release for readers of old reports
            "aegis_version": self.lunas_version,
            "layers": [
                {
                    **asdict(layer),
                    "kind": layer.kind.value,
                    "verdict": layer.verdict.value,
                }
                for layer in self.layers
            ],
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize the report as JSON."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)

    def to_file(self, path: str | Path) -> None:
        """Write the report to ``path`` as JSON."""
        Path(path).write_text(self.to_json(), encoding="utf-8")

    # ----------------------------------------------------------------- views

    def summary(self) -> str:
        """Human-readable single-paragraph summary."""
        passed_count = sum(1 for layer in self.layers if layer.passed())
        failed_count = sum(1 for layer in self.layers if layer.verdict == Verdict.failed)
        skipped_count = sum(1 for layer in self.layers if layer.verdict == Verdict.skipped)
        overall = "PASS" if self.passed else "FAIL"
        first_fail = next(
            (layer for layer in self.layers if layer.verdict == Verdict.failed),
            None,
        )
        if first_fail is not None:
            failed_detail = f" · first failure: {first_fail.name} — {first_fail.summary}"
        else:
            failed_detail = ""
        return (
            f"{overall} · {passed_count} passed · {failed_count} failed "
            f"· {skipped_count} skipped · {self.duration_seconds:.1f}s"
            f"{failed_detail}"
        )

    def failed_layers(self) -> list[LayerResult]:
        """All layers that reported ``failed`` (excludes ``error`` and ``skipped``)."""
        return [layer for layer in self.layers if layer.verdict == Verdict.failed]


__all__ = ["LayerKind", "Verdict", "LayerResult", "ValidationReport"]
