"""Whole-word font evidence for the design_fidelity deterministic override,
and the pytest layer's interpreter fallback chain."""

from __future__ import annotations

from pathlib import Path

from lunas.checks import pytest_check
from lunas.checks.design_fidelity import _font_present


def test_font_present_in_font_family_declaration() -> None:
    css = "h1 { font-family: 'Lora', Georgia, serif; }".lower()
    assert _font_present("Lora", css)


def test_font_present_in_google_fonts_url() -> None:
    html = '<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3&display=swap">'.lower()
    assert _font_present("Source Sans 3", html)


def test_font_not_matched_inside_other_words() -> None:
    code = "body { font-family: system-ui; } /* internal interface */".lower()
    assert not _font_present("Inter", code)


def test_font_absent() -> None:
    assert not _font_present("Lora", "body { font-family: system-ui, sans-serif; }")


def test_resolve_python_prefers_project_venv(tmp_path: Path) -> None:
    venv_py = tmp_path / ".venv" / "bin" / "python"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("")
    assert pytest_check._resolve_python(tmp_path) == str(venv_py)


def test_resolve_python_falls_back_to_running_interpreter(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pytest_check.shutil, "which", lambda name: None)
    monkeypatch.setattr(pytest_check.platform, "system", lambda: "Linux")
    assert pytest_check._resolve_python(tmp_path) == pytest_check.sys.executable
