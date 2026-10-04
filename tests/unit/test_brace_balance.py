"""Unit tests for ``lunas.checks.brace_balance``."""

from __future__ import annotations

from lunas.checks.base import ValidationContext
from lunas.checks.brace_balance import (
    BraceBalanceCheck,
    BraceCounts,
    count_brackets,
)
from lunas.result import LayerKind, Verdict

# ----- count_brackets pure function -----------------------------------


def test_empty_source_is_balanced():
    assert count_brackets("").balanced()


def test_balanced_simple():
    src = "function f() { return [1, 2, 3]; }"
    assert count_brackets(src).balanced()


def test_unbalanced_open_brace():
    """The classic truncation pattern: open brace with no close."""
    src = "function f() { return 1;"
    c = count_brackets(src)
    assert not c.balanced()
    assert c.braces == (1, 0)


def test_unbalanced_close_paren():
    src = "f(1, 2));"  # one extra close paren
    c = count_brackets(src)
    assert not c.balanced()
    assert c.parens == (1, 2)


def test_string_contents_ignored_single_quote():
    src = "const x = '{ this should not count';"
    assert count_brackets(src).balanced()


def test_string_contents_ignored_double_quote():
    src = 'const x = "} { ( ) [ ]";'
    assert count_brackets(src).balanced()


def test_escaped_quote_in_string():
    """\\" inside a string must not terminate the string early."""
    src = 'const x = "she said \\"hello\\" then {";'
    assert count_brackets(src).balanced()


def test_line_comment_contents_ignored():
    src = "const x = 1; // { unbalanced inside line comment"
    assert count_brackets(src).balanced()


def test_line_comment_at_eof():
    """// at the end of file with no trailing newline."""
    src = "const x = 1; // trailing {"
    assert count_brackets(src).balanced()


def test_block_comment_ignored():
    src = "function f() { /* { unbalanced inside */ return 1; }"
    assert count_brackets(src).balanced()


def test_unterminated_block_comment():
    """A /* without */ swallows the rest of the file. The pre-comment
    characters still count; everything after is ignored."""
    src = "{ /* unterminated"
    c = count_brackets(src)
    assert c.braces == (1, 0)
    assert not c.balanced()


def test_template_literal_plain():
    src = "const x = `hello world`;"
    assert count_brackets(src).balanced()


def test_template_interpolation_with_balanced_braces():
    src = "const x = `hello ${name}`;"
    assert count_brackets(src).balanced()


def test_template_interpolation_with_nested_braces():
    """${ { foo: 1 } } — the inner braces are inside the interpolation,
    skipped as a unit, so the outer count stays 0/0."""
    src = "const x = `total: ${({ value: 1 + (2 * 3) }).value}`;"
    assert count_brackets(src).balanced()


def test_template_interpolation_unbalanced_inside_still_balances_outer():
    """If the interpolation has a stray brace (rare, would be a TS error
    anyway), we don't try to repair it — we just consume the ${...} as
    a balanced unit. The outer file still appears balanced. This is
    documented in the module docstring."""
    src = "const x = `${ ( }`;"
    # Outer file has no top-level braces or parens
    c = count_brackets(src)
    assert c.braces == (0, 0)


def test_comment_immediately_inside_string_not_a_comment():
    """// inside a string is just characters, not a comment."""
    src = 'const url = "https://example.com/{path}";'
    assert count_brackets(src).balanced()


def test_block_comment_inside_string_not_a_comment():
    src = 'const x = "/* this is a string */";'
    assert count_brackets(src).balanced()


# ----- BraceCounts class ----------------------------------------------


def test_balanced_method():
    assert BraceCounts((1, 1), (2, 2), (0, 0)).balanced()
    assert not BraceCounts((1, 0), (0, 0), (0, 0)).balanced()


def test_mismatches_method():
    c = BraceCounts((2, 1), (3, 3), (0, 1))
    out = c.mismatches()
    assert any("{=2" in m and "}=1" in m for m in out)
    assert any("[=0" in m and "]=1" in m for m in out)
    assert all("(=3" not in m for m in out)  # parens balanced; not reported


# ----- BraceBalanceCheck layer ----------------------------------------


def test_layer_metadata():
    layer = BraceBalanceCheck()
    assert layer.NAME == "ast_brace_balance"
    assert LayerKind.deterministic == layer.KIND
    assert "node" in layer.APPLIES_TO
    assert "static_html" in layer.APPLIES_TO


def test_layer_applies_to_node():
    layer = BraceBalanceCheck()
    assert layer.applies_to(["node"])
    assert layer.applies_to(["python", "node"])
    assert layer.applies_to(["static_html"])
    assert not layer.applies_to(["python"])
    assert not layer.applies_to([])


def test_layer_passes_on_balanced_file(tmp_path):
    (tmp_path / "app.js").write_text("function hi() { return { ok: true }; }")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed
    assert "All 1" in result.summary
    assert result.details["files_scanned"] == 1


def test_layer_fails_on_truncated_file(tmp_path):
    """The canonical failure mode: agent ran out of tokens mid-function."""
    (tmp_path / "broken.js").write_text("function broken() { return 1;")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert "broken.js" in result.details["mismatch_lines"][0]
    assert "{=1" in result.details["mismatch_lines"][0]


def test_layer_skips_when_no_js_files(tmp_path):
    (tmp_path / "main.py").write_text("def x(): pass")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["python"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.skipped


def test_layer_excludes_node_modules(tmp_path):
    """A broken file inside node_modules must not be reported — it's
    third-party code, not the agent's output."""
    (tmp_path / "app.js").write_text("function ok() {}")
    nm = tmp_path / "node_modules" / "some_pkg"
    nm.mkdir(parents=True)
    (nm / "broken.js").write_text("function broken() {")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed
    assert result.details["files_scanned"] == 1


def test_layer_excludes_dotfolders(tmp_path):
    (tmp_path / "app.js").write_text("function ok() {}")
    git = tmp_path / ".git" / "hooks"
    git.mkdir(parents=True)
    (git / "broken.js").write_text("function {")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed


def test_layer_detects_typescript_files(tmp_path):
    (tmp_path / "broken.tsx").write_text("export const X = () => { return <div>")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert "broken.tsx" in result.details["mismatch_lines"][0]


def test_layer_truncates_long_problem_list(tmp_path):
    """When more than 30 files are broken, only the first 30 are listed
    and ``truncated`` is set."""
    for i in range(35):
        (tmp_path / f"broken_{i}.js").write_text("function broken() {")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.failed
    assert len(result.details["mismatch_lines"]) == 30
    assert result.details["truncated"] is True


def test_layer_respects_scan_cap(tmp_path):
    """The layer scans at most _MAX_FILES_PER_RUN files even if more
    exist — keeps the layer fast on huge repos."""
    for i in range(60):
        (tmp_path / f"app_{i}.js").write_text("function ok() {}")
    layer = BraceBalanceCheck()
    ctx = ValidationContext(code_path=tmp_path, stacks=["node"])
    result = layer.run(ctx)
    assert result.verdict == Verdict.passed
    # Should hit the 50-file cap
    assert result.details["files_scanned"] == 50
