"""Unit tests for the pure helper functions in agents/graph.py."""
from agents.graph import _extract_json, _extract_code_block, _coverage, _read_current_file


# ── _extract_json ────────────────────────────────────────────────────────

def test_extract_json_valid_plain_json():
    text = '{"summary": "do a thing", "files": []}'
    data = _extract_json(text)
    assert data == {"summary": "do a thing", "files": []}


def test_extract_json_wrapped_in_fence():
    text = '```json\n{"summary": "add feature", "files": [{"rel_path": "a.py"}]}\n```'
    data = _extract_json(text)
    assert data["summary"] == "add feature"
    assert data["files"][0]["rel_path"] == "a.py"


def test_extract_json_wrapped_in_plain_fence():
    text = '```\n{"question": "which auth strategy?"}\n```'
    data = _extract_json(text)
    assert data == {"question": "which auth strategy?"}


def test_extract_json_malformed_returns_none():
    text = '{"summary": "broken", "files": [ oops'
    assert _extract_json(text) is None


def test_extract_json_no_braces_returns_none():
    assert _extract_json("just some prose, no json here") is None


def test_extract_json_with_surrounding_prose():
    text = 'Here is the plan:\n{"summary": "x", "files": []}\nHope that helps.'
    data = _extract_json(text)
    assert data == {"summary": "x", "files": []}


# ── _extract_code_block ──────────────────────────────────────────────────

def test_extract_code_block_fenced():
    text = "```python\nx = 1\ny = 2\n```"
    assert _extract_code_block(text) == "x = 1\ny = 2\n"


def test_extract_code_block_fenced_no_language():
    text = "```\nhello world\n```"
    assert _extract_code_block(text) == "hello world\n"


def test_extract_code_block_no_fence_returns_stripped_text():
    text = "  just plain text, no fence  \n"
    assert _extract_code_block(text) == "just plain text, no fence"


# ── _coverage ─────────────────────────────────────────────────────────────

def test_coverage_empty_when_both_blank():
    assert _coverage("", "") == "empty"


def test_coverage_sparse_below_threshold():
    assert _coverage("short", "") == "sparse"


def test_coverage_partial_between_thresholds():
    sgl = "x" * 300
    assert _coverage(sgl, "") == "partial"


def test_coverage_complete_above_threshold():
    sgl = "x" * 900
    assert _coverage(sgl, "") == "complete"


def test_coverage_combines_sgl_and_commits():
    sgl = "x" * 500
    commits = "y" * 400
    assert _coverage(sgl, commits) == "complete"


def test_coverage_boundary_at_200_is_sparse():
    # combined length exactly 200 is not > 200, so still sparse.
    assert _coverage("x" * 200, "") == "sparse"


def test_coverage_boundary_at_800_is_partial():
    # combined length exactly 800 is not > 800, so still partial.
    assert _coverage("x" * 800, "") == "partial"


# ── _read_current_file ───────────────────────────────────────────────────
# Regression coverage: the coder used to rewrite files it had never seen,
# because only exemplar/wiring files (chosen by role heuristics) were ever
# read into context. _read_current_file lets the coder node read the actual
# rewrite target directly.

def test_read_current_file_returns_content(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    assert _read_current_file(str(tmp_path), "app.py") == "x = 1\n"


def test_read_current_file_missing_returns_none(tmp_path):
    assert _read_current_file(str(tmp_path), "nope.py") is None


def test_read_current_file_no_repo_root_returns_none():
    assert _read_current_file("", "app.py") is None


def test_read_current_file_path_violation_returns_none(tmp_path):
    assert _read_current_file(str(tmp_path), "../../etc/passwd") is None


def test_read_current_file_truncates_at_max_bytes(tmp_path):
    (tmp_path / "big.py").write_text("x" * 100)
    assert len(_read_current_file(str(tmp_path), "big.py", max_bytes=10)) == 10
