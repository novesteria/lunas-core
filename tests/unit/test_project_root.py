"""An upload whose code sits in a subfolder (deneme-1/kod/index.html) was
reported as "fail, 0 issues" with every layer skipped."""

from pathlib import Path

from lunas.stack_detection import detect_stacks, find_project_root


def _yaz(p: Path, text: str = "x") -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_nested_project_is_found(tmp_path: Path) -> None:
    _yaz(tmp_path / "deneme-1" / "kod" / "index.html", "<html></html>")
    _yaz(tmp_path / "deneme-1" / "KAYIT.md")
    root = find_project_root(tmp_path)
    assert root == tmp_path / "deneme-1" / "kod"
    assert detect_stacks(root) == ["static_html"]


def test_top_level_project_is_kept(tmp_path: Path) -> None:
    _yaz(tmp_path / "index.html")
    _yaz(tmp_path / "sub" / "package.json", "{}")
    assert find_project_root(tmp_path) == tmp_path


def test_backend_frontend_split_is_kept(tmp_path: Path) -> None:
    _yaz(tmp_path / "backend" / "requirements.txt")
    _yaz(tmp_path / "frontend" / "package.json", "{}")
    assert find_project_root(tmp_path) == tmp_path


def test_two_candidates_at_same_depth_keep_root(tmp_path: Path) -> None:
    _yaz(tmp_path / "a" / "x" / "index.html")
    _yaz(tmp_path / "b" / "y" / "index.html")
    assert find_project_root(tmp_path) == tmp_path


def test_node_modules_is_ignored(tmp_path: Path) -> None:
    _yaz(tmp_path / "node_modules" / "pkg" / "package.json", "{}")
    _yaz(tmp_path / "app" / "web" / "index.html")
    assert find_project_root(tmp_path) == tmp_path / "app" / "web"
