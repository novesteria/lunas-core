"""Strip Markdown code fences from LLM output.

LLM responses to validator prompts sometimes wrap structured output
(JSON, code) in triple-backtick fences:

    ```json
    { "verdict": "fail" }
    ```

This module strips the fence so downstream parsing sees the raw payload.
Public utility — exported from the lunas package because external
callers may pre-process LLM responses before passing them to a custom
LLMClient.
"""

from __future__ import annotations

import re

# Match ```<optional_language>\n ... \n``` with optional surrounding whitespace.
# DOTALL so \n inside the body is captured.
_FENCE_RE = re.compile(
    r"^\s*```(?:[a-zA-Z0-9_+-]*)?\n(.*?)\n```\s*$",
    re.DOTALL,
)


def strip_code_fence(text: str) -> str:
    """Return ``text`` without its surrounding triple-backtick fence.

    If ``text`` is not fenced, it is returned unchanged (stripped of
    leading/trailing whitespace).

    Examples:
        >>> strip_code_fence("```json\\n{}\\n```")
        '{}'
        >>> strip_code_fence("```\\nhello\\n```")
        'hello'
        >>> strip_code_fence("no fence here")
        'no fence here'
        >>> strip_code_fence("")
        ''
    """
    if not text:
        return text
    match = _FENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text.strip()


__all__ = ["strip_code_fence"]
