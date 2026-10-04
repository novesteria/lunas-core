"""Shared utilities for the LLM-judge layers (#23 + #24).

Centralizes:

- Code-blob collection with a budget (so the judge prompt stays under
  the LLM's context window).
- JSON parsing of model responses (handles ``` fences and embedded
  prose).
- ``DesignDNA`` empty-check helper.

The LLM layers themselves live in
``lunas.checks.design_fidelity`` and ``lunas.checks.feature_coverage``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lunas.design_dna import DesignDNA

_CODE_EXTENSIONS_DEFAULT: tuple[str, ...] = (
    ".html", ".htm", ".js", ".mjs", ".cjs",
    ".jsx", ".tsx", ".ts", ".css",
    ".py",
)


def collect_code_blob(
    root: Path,
    *,
    budget_bytes: int = 28_000,
    extensions: tuple[str, ...] = _CODE_EXTENSIONS_DEFAULT,
) -> str:
    """Concatenate readable files under ``root`` into a single budgeted blob.

    Walks the tree in glob order, skips hidden dirs and ``node_modules``,
    truncates the FIRST file that would overflow the budget (with a
    note marker) and stops there. Returns ``""`` when nothing is
    readable — caller treats that as "skip the layer".
    """
    code_blobs: list[str] = []
    total_size = 0

    for ext in extensions:
        for p in root.rglob(f"*{ext}"):
            if not p.is_file():
                continue
            try:
                rel_parts = p.relative_to(root).parts
            except ValueError:
                continue
            if any(part.startswith(".") or part == "node_modules" for part in rel_parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = p.relative_to(root).as_posix()
            chunk = f"=== {rel} ===\n{text}\n"
            if total_size + len(chunk) > budget_bytes:
                avail = max(0, budget_bytes - total_size - 200)
                if avail > 500:
                    chunk = f"=== {rel} (truncated) ===\n{text[:avail]}\n"
                    code_blobs.append(chunk)
                    total_size += len(chunk)
                return "\n".join(code_blobs)
            code_blobs.append(chunk)
            total_size += len(chunk)

    return "\n".join(code_blobs)


def parse_json_verdict(raw: str) -> dict[str, Any] | None:
    """Parse the LLM's response as JSON, with two fallbacks.

    Tries:
    1. ``json.loads`` on the stripped string (works for clean responses).
    2. Strip ``` fences and retry.
    3. Find the first ``{ … }`` block via regex and parse it.

    Returns the parsed dict, or ``None`` if parsing fails at every step.
    Callers map ``None`` to "judge unparseable — skip / fallback".
    """
    if not raw or not raw.strip():
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```\w*\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?\s*```$", "", cleaned)
        cleaned = cleaned.strip()
    try:
        out = json.loads(cleaned)
        return out if isinstance(out, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
        return out if isinstance(out, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def design_dna_is_empty(dna: DesignDNA | None) -> bool:
    """True if ``dna`` carries no actionable design content.

    A brief is "empty" when nobody filled in a palette, fonts, tone,
    or philosophy — quick-mode users get this when they skip the brief
    step. The LLM-judge layers skip cleanly when the brief is empty
    (no API cost, no false-positive).
    """
    if dna is None:
        return True
    pal = dna.brand.palette
    fonts = dna.brand.fonts
    has_palette = any(getattr(pal, k, "") for k in ("primary", "secondary", "accent", "bg", "fg"))
    has_fonts = bool(getattr(fonts, "heading", "")) or bool(getattr(fonts, "body", ""))
    has_tone = bool(dna.brand.tone)
    has_philosophy = bool(dna.philosophy.id)
    return not (has_palette or has_fonts or has_tone or has_philosophy)


__all__ = [
    "collect_code_blob",
    "parse_json_verdict",
    "design_dna_is_empty",
]
