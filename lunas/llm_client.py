"""Pluggable LLM client for layers that need model judgment.

The validator has two LLM-using layers (design fidelity, feature
coverage). They consume an ``LLMClient`` Protocol so users can plug in
their own backend without forking Lunas.

Lunas ships with one implementation, ``AnthropicClient``, which uses
the official ``anthropic`` Python SDK. It is an optional dependency:

    pip install lunas-validator[anthropic]

Users who don't have an Anthropic key, or who prefer OpenAI / local
Llama / cached responses, can pass any object matching the Protocol.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    """A pluggable LLM client.

    Implementations should be async-safe (the validator pipeline calls
    judge() from inside an event loop) and stateless across calls.
    """

    async def judge(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Send a judgment prompt to the model and return the text response.

        Args:
            prompt: The full prompt, including any system context. Lunas
                does not split into system/user automatically; callers
                pre-format.
            max_tokens: Maximum tokens to generate. Validator layers
                generally need very short responses (yes/no or a small
                JSON object), so the default is conservative.
            temperature: Sampling temperature. Defaults to 0 for
                reproducible verdicts.

        Returns:
            The model's response text. The layer is responsible for
            parsing (e.g. extracting a JSON block).
        """
        ...


class AnthropicClient:
    """Default LLM client backed by the Anthropic SDK.

    Requires the ``anthropic`` optional dependency:

        pip install lunas-validator[anthropic]

    And ``ANTHROPIC_API_KEY`` in the environment (or passed explicitly).

    Example:
        client = AnthropicClient()  # reads ANTHROPIC_API_KEY from env
        client = AnthropicClient(api_key="sk-ant-...", model="claude-sonnet-4-6")
    """

    DEFAULT_MODEL = "claude-opus-4-7"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
    ) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "AnthropicClient requires the 'anthropic' package. "
                "Install with: pip install lunas-validator[anthropic]"
            ) from exc

        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not resolved_key:
            raise ValueError(
                "AnthropicClient needs an API key. Pass api_key=... or set "
                "ANTHROPIC_API_KEY in the environment."
            )

        self._client = anthropic.AsyncAnthropic(api_key=resolved_key)
        self._model = model

    async def judge(
        self,
        prompt: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        # Some newer Claude models (e.g. Opus 4.7) reject the
        # ``temperature`` parameter outright. Pass it only when the
        # caller explicitly overrode the default; otherwise let the
        # API choose its own.
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature != 0.0:
            kwargs["temperature"] = temperature

        response = await self._client.messages.create(**kwargs)
        # response.content is a list of content blocks; we take the
        # text from the first block (judgment prompts return a single
        # text block by convention).
        for block in response.content:
            if getattr(block, "type", None) == "text":
                return block.text  # type: ignore[no-any-return]
        return ""


__all__ = ["LLMClient", "AnthropicClient"]
