"""DesignDNA dataclass and brief.json loader.

The brief is the contract between user intent and validator judgment.
LLM-judge and hybrid layers compare generated code against the brief;
when the brief is missing, those layers skip with a clear message.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Palette:
    primary: str
    secondary: str
    accent: str
    bg: str
    fg: str


@dataclass(frozen=True)
class Fonts:
    heading: str
    body: str


@dataclass(frozen=True)
class Brand:
    has_logo: bool
    palette: Palette
    fonts: Fonts
    tone: list[str]


@dataclass(frozen=True)
class Philosophy:
    id: str
    label: str
    rules: dict[str, Any]


@dataclass(frozen=True)
class DesignDNA:
    """The 'brief' that drives design-fidelity and feature-coverage layers."""

    version: int
    archetype: str
    brand: Brand
    philosophy: Philosophy
    density: str
    motion: str
    intent: str = ""
    features: list[str] = field(default_factory=list)
    notes: str = ""
    stack: dict[str, str] = field(default_factory=dict)


def load_brief(path: str | Path) -> DesignDNA:
    """Load a brief.json file into a typed DesignDNA instance.

    Raises ``ValueError`` if the JSON is missing required fields or has
    a version that this Lunas release doesn't understand.
    """
    raw_path = Path(path)
    if not raw_path.exists():
        raise FileNotFoundError(f"Brief not found: {raw_path}")

    data: dict[str, Any] = json.loads(raw_path.read_text(encoding="utf-8"))

    version = data.get("version")
    if version != 1:
        raise ValueError(
            f"Unsupported brief version: {version!r}. This Lunas release "
            f"reads version 1 only."
        )

    try:
        return DesignDNA(
            version=version,
            archetype=data["archetype"],
            intent=data.get("intent", ""),
            stack=data.get("stack", {}),
            brand=Brand(
                has_logo=data["brand"]["has_logo"],
                palette=Palette(**data["brand"]["palette"]),
                fonts=Fonts(**data["brand"]["fonts"]),
                tone=data["brand"]["tone"],
            ),
            philosophy=Philosophy(
                id=data["philosophy"]["id"],
                label=data["philosophy"]["label"],
                rules=data["philosophy"]["rules"],
            ),
            density=data["density"],
            motion=data["motion"],
            features=data.get("features", []),
            notes=data.get("notes", ""),
        )
    except KeyError as exc:
        raise ValueError(f"Brief missing required field: {exc.args[0]}") from exc


__all__ = ["DesignDNA", "Brand", "Palette", "Fonts", "Philosophy", "load_brief"]
