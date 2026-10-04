"""``CheckLayer`` — abstract base for every validation pass.

Each of Lunas's 24 layers is a ``CheckLayer`` subclass. The pipeline
instantiates them, calls ``run()``, and collects the ``LayerResult``s
into a ``ValidationReport``.

Subclasses should be:

- **Stateless across runs.** ``run()`` reads its input from the
  ``ValidationContext`` and returns a fresh ``LayerResult``. No
  mutation of class or instance state.
- **Async where they need to await.** Most deterministic layers are
  CPU/IO-bound on subprocess or file I/O; LLM-using layers await the
  client. Subclasses pick ``run()`` or ``async run_async()``.
- **Targeted to a stack.** ``applies_to(stacks)`` returns True only if
  the layer is relevant. A Python-AST layer should not run on a pure
  Node project.

See ``docs/LAYER_INDEX.md`` for the canonical list and per-layer
documentation.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lunas.result import LayerKind, LayerResult, Verdict


@dataclass(frozen=True)
class ValidationContext:
    """Read-only input passed to every layer.

    Layers receive the same context; they should not mutate it. The
    pipeline collects layer results separately.
    """

    code_path: Path
    """The local directory containing the code to validate."""

    stacks: list[str]
    """Stacks detected in the code (e.g. ``["python", "node"]``)."""

    brief: Any | None = None
    """Optional ``DesignDNA`` brief. None when no brief was provided."""

    timeout_per_command: int = 300
    """Per-subprocess timeout in seconds (default: 5 minutes)."""

    llm_client: Any | None = None
    """Optional LLM client. None when ``no_llm=True`` or no client passed."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Free-form bag of additional context layers may need (e.g.
    parsed config files cached by an earlier layer to avoid re-parsing)."""


class CheckLayer(abc.ABC):
    """Base class for all validation layers.

    Subclasses implement ``run`` (sync) or override ``run_async``
    (async) and must declare ``NAME``, ``KIND``, and ``APPLIES_TO``.
    """

    # ---- subclass contract ----

    NAME: str = ""
    """Stable layer identifier. Used in expected.json fixtures, in CLI
    output, and in bench diffs. Snake_case (e.g. ``build_install``,
    ``ast_python_imports``)."""

    KIND: LayerKind = LayerKind.deterministic
    """``LayerKind.deterministic`` for layers with no LLM call,
    ``llm_judge`` for pure-LLM judgment, ``hybrid`` for LLM with
    deterministic override."""

    APPLIES_TO: tuple[str, ...] = ()
    """Tuple of stack names this layer applies to. Empty tuple = applies
    to all stacks. (E.g. a Python AST check has ``("python",)``; a
    cross-stack check like brace balance might have multiple.)"""

    DESCRIPTION: str = ""
    """One-line human-readable description shown in CLI ``--verbose``
    mode and in the docs auto-generated index."""

    # ---- subclass overrides ----

    def applies_to(self, stacks: list[str]) -> bool:
        """Return True if this layer should run for the detected stacks.

        Default: True if ``APPLIES_TO`` is empty (cross-stack layer) or
        any of the stacks in ``stacks`` match.
        """
        if not self.APPLIES_TO:
            return True
        return any(stack in self.APPLIES_TO for stack in stacks)

    async def run_async(self, ctx: ValidationContext) -> LayerResult:
        """Async entry point. Default delegates to ``run()`` (sync).

        Override this directly if the layer needs to ``await`` (LLM
        calls, async subprocess primitives). Otherwise override ``run``.
        """
        return self.run(ctx)

    @abc.abstractmethod
    def run(self, ctx: ValidationContext) -> LayerResult:
        """Synchronous run. Subclasses must implement at least one of
        ``run`` or ``run_async``. The default ``run_async`` calls this."""
        raise NotImplementedError

    # ---- helpers for subclasses ----

    def _result(
        self,
        verdict: Verdict,
        summary: str,
        *,
        start_time: float,
        details: dict[str, Any] | None = None,
        override_fired: bool = False,
    ) -> LayerResult:
        """Build a ``LayerResult`` with this layer's name + kind + a
        duration computed from ``start_time``.
        """
        return LayerResult(
            name=self.NAME,
            kind=self.KIND,
            verdict=verdict,
            duration_seconds=time.monotonic() - start_time,
            summary=summary,
            details=details or {},
            override_fired=override_fired,
        )

    def _skip(self, reason: str) -> LayerResult:
        """Convenience: build a skipped result with zero duration."""
        return LayerResult(
            name=self.NAME,
            kind=self.KIND,
            verdict=Verdict.skipped,
            duration_seconds=0.0,
            summary=reason,
            details={},
        )


__all__ = ["CheckLayer", "ValidationContext"]
