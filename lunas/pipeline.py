"""``ValidationPipeline`` — orchestrates the layer sequence.

The pipeline is intentionally a thin coordinator:

1. Detect stacks present in the code directory.
2. For each registered layer, decide whether it applies, then run it.
3. Collect results, decide overall pass/fail, return a ValidationReport.

Most of the validator's intelligence lives in the individual ``CheckLayer``
subclasses under ``lunas.checks.``. The pipeline doesn't know what any
layer does — it just runs them and aggregates outcomes.

Layer-extraction status (May 2026):
    The pipeline currently runs zero layers — the registry in
    ``lunas.checks.__init__`` is empty pending Phase 1.2 extraction.
    The pipeline class is correct; it gets useful as layers land.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from lunas.checks import all_layers
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.llm_client import LLMClient
from lunas.result import LayerResult, ValidationReport, Verdict
from lunas.stack_detection import detect_stacks

if TYPE_CHECKING:
    from lunas.design_dna import DesignDNA


class ValidationPipeline:
    """Run all registered check layers against a code directory.

    Most users don't construct this directly — they call ``lunas.validate``
    which builds a pipeline with sensible defaults. Instantiate this
    class only when you need to customize behavior (custom LLM client,
    different timeout, layer subset).

    Args:
        llm_client: Backend for LLM-using layers. If None and ``no_llm``
            is also False, the pipeline attempts to construct an
            ``AnthropicClient`` lazily — which raises if neither the
            ``anthropic`` package nor an ``ANTHROPIC_API_KEY`` is
            available.
        no_llm: If True, all LLM-using layers (``llm_judge`` and
            ``hybrid`` kinds) are skipped. Useful for CI smoke tests.
        timeout_per_command: Per-subprocess timeout in seconds. Applied
            to layers that invoke ``npm install``, ``pytest``, etc.
            Default 300.
        layers: Optional explicit layer list. When None, uses the
            registry from ``lunas.checks``. Pass a subset for test
            isolation or a custom layer mix.
    """

    def __init__(
        self,
        *,
        llm_client: LLMClient | None = None,
        no_llm: bool = False,
        timeout_per_command: int = 300,
        layers: list[type[CheckLayer]] | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._no_llm = no_llm
        self._timeout = timeout_per_command
        self._layer_classes = layers if layers is not None else all_layers()

    # ---- public API ----

    async def validate(
        self,
        code_path: str | Path,
        *,
        brief: DesignDNA | None = None,
    ) -> ValidationReport:
        """Run the pipeline against ``code_path``."""
        start = time.monotonic()
        path = Path(code_path).resolve()

        stacks = detect_stacks(path)
        ctx = ValidationContext(
            code_path=path,
            stacks=stacks,
            brief=brief,
            timeout_per_command=self._timeout,
            llm_client=self._llm_client if not self._no_llm else None,
        )

        results: list[LayerResult] = []
        for layer_cls in self._layer_classes:
            layer = layer_cls()
            if not layer.applies_to(stacks):
                results.append(layer._skip(reason=f"stack mismatch: {stacks}"))
                continue
            try:
                result = await layer.run_async(ctx)
            except Exception as exc:  # layer crashed; treat as error
                result = LayerResult(
                    name=layer.NAME,
                    kind=layer.KIND,
                    verdict=Verdict.error,
                    duration_seconds=0.0,
                    summary=f"Layer crashed: {type(exc).__name__}: {exc}",
                    details={"exception": repr(exc)},
                )
            results.append(result)

        # Aggregate verdict: passed iff every non-skipped layer is passed.
        non_skipped = [r for r in results if r.verdict != Verdict.skipped]
        overall_passed = bool(non_skipped) and all(
            r.verdict == Verdict.passed for r in non_skipped
        )

        # Import here to avoid circular import with __init__.
        from lunas import __version__
        return ValidationReport(
            passed=overall_passed,
            layers=results,
            stacks_detected=stacks,
            code_path=str(path),
            duration_seconds=time.monotonic() - start,
            lunas_version=__version__,
        )


__all__ = ["ValidationPipeline"]
