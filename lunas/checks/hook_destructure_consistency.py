"""Layer #11 — consumer destructures fields the hook doesn't return.

Catches the React-hook variant of "type drift": the hook author
returns ``{ a, b }`` but a consumer writes
``const { a, b, c } = useThing();`` — ``c`` is ``undefined`` and the
next line that touches it explodes at render time.

``tsc`` would catch this *if* the hook had an explicit generic return
type. Agent-written hooks rarely declare one — the failure is silent
until first use.

Strategy:

1. Scan every ``.ts/.tsx/.js/.jsx`` file. For each function named
   ``use*`` (custom hook), extract the keys of the **last** top-level
   ``return { … }`` literal. Support both:

       function useX() { … return { a, b }; }
       const useX = () => ({ a, b })
       const useX = () => { … return { a, b }; }

2. For each ``const { a, b, c } = useX(…)`` consumer, verify the
   destructured names are a subset of the hook's return keys.

3. If the hook's return shape can't be extracted confidently (spread,
   conditional returns), drop the hook from the audit — silence beats
   false positives.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from lunas.checks._ts_helpers import find_ts_sources
from lunas.checks.base import CheckLayer, ValidationContext
from lunas.result import LayerKind, LayerResult, Verdict

_FUNC_DECL_RE = re.compile(
    r"""(?:export\s+)?(?:async\s+)?function\s+(use[A-Z]\w*)\s*\([^)]*\)\s*(?::[^{]+)?\s*\{""",
    re.MULTILINE,
)
_ARROW_RE = re.compile(
    r"""(?:export\s+)?const\s+(use[A-Z]\w*)\s*(?::[^=]+)?=\s*(?:async\s+)?\(?[^)]*\)?\s*=>\s*""",
    re.MULTILINE,
)
_RETURN_OBJ_RE = re.compile(r"return\s*\{")
_CONSUMER_RE = re.compile(
    r"""const\s*\{([^}]+)\}\s*=\s*(use[A-Z]\w*)\s*\(""",
    re.MULTILINE,
)
_BARE_KEY_RE = re.compile(r"^\w+$")


def _find_block_end(src: str, start_brace_idx: int) -> int:
    """Match ``{ … }`` accounting for string literals."""
    depth = 1
    i = start_brace_idx + 1
    in_str: str | None = None
    while i < len(src) and depth > 0:
        c = src[i]
        if in_str:
            if c == in_str and src[i - 1] != "\\":
                in_str = None
        elif c in "\"'`":
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return i


def _keys_from_object_literal(blob: str) -> set[str] | None:
    """Parse keys from a ``{ a, b, c: x }`` blob.

    Returns ``None`` when the blob contains a spread or a computed key
    (we can't enumerate confidently). Returns an empty set if the body
    has no recognizable keys.
    """
    stripped = blob.strip()
    if not stripped or "..." in stripped:
        return None
    keys: set[str] = set()
    depth = 0
    in_str: str | None = None
    current = ""
    chunks: list[str] = []
    i = 0
    while i < len(stripped):
        c = stripped[i]
        if in_str:
            if c == in_str and stripped[i - 1] != "\\":
                in_str = None
            current += c
        elif c in "\"'`":
            in_str = c
            current += c
        elif c in "({[":
            depth += 1
            current += c
        elif c in ")}]":
            depth -= 1
            current += c
        elif c == "," and depth == 0:
            chunks.append(current)
            current = ""
        else:
            current += c
        i += 1
    if current.strip():
        chunks.append(current)

    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("["):
            return None  # computed key — bail
        key = chunk.split(":", 1)[0].strip()
        key = key.split("(", 1)[0].strip()
        key = key.split("?")[0].strip()
        if key and _BARE_KEY_RE.match(key):
            keys.add(key)
    return keys


def _extract_last_return_keys(body: str) -> set[str] | None:
    """Within a function body, find the *last* top-level
    ``return { … }`` and parse its keys.
    """
    last: set[str] | None = None
    found_any = False
    for r in _RETURN_OBJ_RE.finditer(body):
        ret_brace = r.end() - 1
        ret_close = _find_block_end(body, ret_brace)
        result = _keys_from_object_literal(body[ret_brace + 1: ret_close - 1])
        found_any = True
        last = result
    if not found_any:
        return None
    return last


def collect_hook_returns(sources: list[Path]) -> dict[str, set[str]]:
    """Walk ``sources`` and return ``hook_name → returned keys`` for every
    custom ``use*`` hook whose return shape we can extract confidently.

    Hooks whose return shape we *can't* extract are omitted — caller
    treats absence as "skip this hook".
    """
    raw: dict[str, set[str] | None] = {}

    for src_file in sources:
        try:
            src = src_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for m in _FUNC_DECL_RE.finditer(src):
            hook = m.group(1)
            body_start = m.end() - 1
            body_end = _find_block_end(src, body_start)
            body = src[body_start + 1: body_end - 1]
            keys = _extract_last_return_keys(body)
            raw[hook] = keys

        for m in _ARROW_RE.finditer(src):
            hook = m.group(1)
            tail = m.end()
            j = tail
            while j < len(src) and src[j] in " \t\r\n":
                j += 1
            if j >= len(src):
                continue
            if src[j] == "(":
                k = j + 1
                while k < len(src) and src[k] != "{":
                    if src[k] not in " \t\r\n":
                        break
                    k += 1
                if k < len(src) and src[k] == "{":
                    end = _find_block_end(src, k)
                    keys = _keys_from_object_literal(src[k + 1: end - 1])
                    raw[hook] = keys
            elif src[j] == "{":
                end = _find_block_end(src, j)
                body = src[j + 1: end - 1]
                keys = _extract_last_return_keys(body)
                raw[hook] = keys

    return {h: k for h, k in raw.items() if k is not None and k}


def find_hook_destructure_problems(
    root: Path,
) -> tuple[list[dict[str, str | list[str] | int]], int, int]:
    """Walk ``root`` and report consumer/hook shape mismatches.

    Returns ``(problems, files_scanned, hooks_audited)``.
    """
    sources = find_ts_sources(root)
    if not sources:
        return [], 0, 0

    hooks = collect_hook_returns(sources)
    if not hooks:
        return [], len(sources), 0

    problems: list[dict[str, str | list[str] | int]] = []
    for src_file in sources:
        try:
            src = src_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = src_file.relative_to(root).as_posix()
        for m in _CONSUMER_RE.finditer(src):
            blob = m.group(1)
            hook = m.group(2)
            if hook not in hooks:
                continue
            wanted: list[str] = []
            for chunk in blob.split(","):
                chunk = chunk.strip()
                if not chunk or chunk.startswith("..."):
                    continue
                name = chunk.split(":")[0].split("=")[0].strip()
                if name:
                    wanted.append(name)
            missing = [w for w in wanted if w not in hooks[hook]]
            if missing:
                line_no = src[: m.start()].count("\n") + 1
                problems.append({
                    "file": rel,
                    "line": line_no,
                    "hook": hook,
                    "returned": sorted(hooks[hook]),
                    "missing": missing,
                })

    return problems, len(sources), len(hooks)


class HookDestructureConsistencyCheck(CheckLayer):
    """Layer #11 — hook consumers must destructure only fields the hook returns."""

    NAME = "hook_destructure_consistency"
    KIND = LayerKind.deterministic
    APPLIES_TO = ("node",)
    DESCRIPTION = (
        "When a consumer destructures `const { a, b } = useX()`, "
        "`{a, b}` must be a subset of useX's actual return shape. "
        "Catches the canonical hook-return-drift bug that triggers an "
        "`undefined`-method crash at first render."
    )

    def run(self, ctx: ValidationContext) -> LayerResult:
        start = time.monotonic()
        root = ctx.code_path
        if not root.is_dir():
            return self._skip("code_path is not a directory")

        if not find_ts_sources(root):
            return self._skip("No TS/JS files in input")

        problems, scanned, audited = find_hook_destructure_problems(root)

        if audited == 0:
            return self._skip(
                "No custom `use*` hooks with extractable return shape"
            )

        if problems:
            shown = problems[:15]
            return self._result(
                Verdict.failed,
                summary=(
                    f"{len(problems)} hook consumer(s) destructure fields "
                    f"the hook does not return ({audited} hook(s) audited, "
                    f"{scanned} file(s) scanned)"
                ),
                start_time=start,
                details={
                    "files_scanned": scanned,
                    "hooks_audited": audited,
                    "problems": shown,
                    "truncated": len(problems) > 15,
                },
            )

        return self._result(
            Verdict.passed,
            summary=(
                f"{audited} hook(s) verified across {scanned} file(s); "
                f"no destructure drift"
            ),
            start_time=start,
            details={"files_scanned": scanned, "hooks_audited": audited},
        )


__all__ = [
    "HookDestructureConsistencyCheck",
    "collect_hook_returns",
    "find_hook_destructure_problems",
]
