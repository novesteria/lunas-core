"""Lunas — a deterministic validator for AI-generated code.

Public API:

    >>> import lunas
    >>> report = lunas.validate("./my-ai-generated-code")
    >>> report.passed
    True

The core surface is small and stable:

- ``validate(path, **kwargs)`` — the one-line happy path
- ``ValidationPipeline`` — instantiate for advanced configuration
- ``ValidationReport`` / ``LayerResult`` — output dataclasses
- ``LLMClient`` (Protocol) — pluggable backend for LLM-using layers
- ``AnthropicClient`` — default LLM implementation (requires anthropic SDK)

See ``docs/`` in the source repo for the layer index, methodology, and
extraction plan.
"""

__version__ = "0.1.0"

from lunas.design_dna import DesignDNA, load_brief
from lunas.llm_client import LLMClient
from lunas.pipeline import ValidationPipeline
from lunas.result import LayerResult, ValidationReport

# The default LLM client requires the optional anthropic dependency.
# Import lazily so `import lunas` works in environments without it.
try:
    from lunas.llm_client import AnthropicClient
except ImportError:  # anthropic SDK not installed
    AnthropicClient = None  # type: ignore[assignment,misc]


async def validate(
    path: str,
    *,
    brief: DesignDNA | None = None,
    llm_client: LLMClient | None = None,
    no_llm: bool = False,
) -> ValidationReport:
    """Validate a directory of code against the Lunas layer pipeline.

    Args:
        path: Local directory containing the code to validate.
        brief: Optional design brief. When omitted, design-fidelity and
            feature-coverage layers are skipped (they need the brief to
            judge against).
        llm_client: Pluggable LLM backend. When omitted, ``AnthropicClient``
            is used (requires the ``anthropic`` extra: ``pip install
            lunas-validator[anthropic]`` and ``ANTHROPIC_API_KEY`` env var).
        no_llm: When True, skip all LLM-using layers (design fidelity,
            feature coverage). Useful for CI smoke tests without API keys.

    Returns:
        A ``ValidationReport`` with per-layer results and an overall verdict.
    """
    pipeline = ValidationPipeline(llm_client=llm_client, no_llm=no_llm)
    return await pipeline.validate(path, brief=brief)


__all__ = [
    "__version__",
    "validate",
    "ValidationPipeline",
    "ValidationReport",
    "LayerResult",
    "LLMClient",
    "AnthropicClient",
    "DesignDNA",
    "load_brief",
]
