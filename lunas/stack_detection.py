"""Detect what stacks live in a directory.

Lunas's first-release scope is Python + Node.js (TS / JS) + static HTML.
``detect_stacks(path)`` returns a list like ``["python", "node"]`` so
the pipeline knows which layer subsets to run.

Detection is intentionally simple — presence of build-config files,
not deep parsing — because the goal is *which validators to invoke*,
not *full project analysis*. Each layer does its own deep work later.
"""

from __future__ import annotations

from pathlib import Path

# Build-config files that signal each stack's presence.
_STACK_SIGNALS: dict[str, tuple[str, ...]] = {
    "python": (
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
    ),
    "node": (
        "package.json",
    ),
    "static_html": (
        "index.html",
    ),
}


def detect_stacks(code_path: str | Path) -> list[str]:
    """Return the list of detected stacks for a directory.

    A directory can contain multiple stacks (e.g. a Python backend with
    an embedded ``frontend/`` Node project). The returned list is in
    canonical order: ``python``, ``node``, ``static_html``.

    If no recognized stack is found, returns an empty list. The pipeline
    treats this as "nothing to validate" — every layer skips.

    Edge case: a project with both ``package.json`` and ``index.html``
    is detected as Node (the ``package.json`` wins because static_html
    layers don't run when a build tool is involved).
    """
    path = Path(code_path)
    if not path.is_dir():
        return []

    detected: list[str] = []

    # Walk shallowly — we only want top-level signals plus one level of
    # nesting (a `frontend/` dir is common). Deeper nesting is left to
    # the layers themselves to handle.
    candidates: list[Path] = [path]
    for child in path.iterdir():
        if child.is_dir() and not child.name.startswith("."):
            candidates.append(child)

    for stack, signals in _STACK_SIGNALS.items():
        for candidate in candidates:
            if any((candidate / signal).exists() for signal in signals):
                if stack not in detected:
                    detected.append(stack)
                break

    # static_html alone if neither python nor node found
    if "node" in detected and "static_html" in detected:
        # node + static_html → node wins (the index.html is just the build target)
        detected.remove("static_html")

    return detected


__all__ = ["detect_stacks"]
