"""Unit tests for the pure helper functions in agents/graph.py."""
import json

import pytest
from langchain_core.messages import HumanMessage

from agents.graph import (
    _extract_json, _extract_code_block, _coverage, _read_current_file,
    initial_state, make_planner_node,
)


class _FakeResponse:
    def __init__(self, content: str):
        self.content = content


class _FakeLLM:
    """Returns one canned response per call, in order — enough to drive make_planner_node
    without a real model."""
    def __init__(self, *responses: str):
        self._responses = list(responses)

    async def ainvoke(self, messages):
        return _FakeResponse(self._responses.pop(0))


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


# ── make_planner_node: op normalization against the real filesystem ──────
# Regression: the planner repeatedly said "create" for README.md even though
# routers/repos.py pre-writes one before autobuild ever runs, and
# validate_write correctly rejects a "create" onto an existing file - so the
# write silently never landed. The planner now corrects op against what's
# actually on disk instead of trusting the model's guess.

@pytest.mark.asyncio
async def test_planner_flips_create_to_rewrite_for_existing_file(tmp_path):
    (tmp_path / "README.md").write_text("# stub\n")
    llm = _FakeLLM(json.dumps({
        "summary": "update docs",
        "files": [{"rel_path": "README.md", "op": "create", "intent": "add usage docs"}],
    }))
    planner = make_planner_node(llm)
    state = initial_state([HumanMessage(content="add docs")], repo_id="r1", repo_root=str(tmp_path))
    result = await planner(state)
    assert result["plan"] == [{"rel_path": "README.md", "op": "rewrite", "intent": "add usage docs"}]


@pytest.mark.asyncio
async def test_planner_flips_rewrite_to_create_for_missing_file(tmp_path):
    llm = _FakeLLM(json.dumps({
        "summary": "add config",
        "files": [{"rel_path": "config.json", "op": "rewrite", "intent": "add config"}],
    }))
    planner = make_planner_node(llm)
    state = initial_state([HumanMessage(content="add config")], repo_id="r1", repo_root=str(tmp_path))
    result = await planner(state)
    assert result["plan"] == [{"rel_path": "config.json", "op": "create", "intent": "add config"}]


@pytest.mark.asyncio
async def test_planner_leaves_correct_op_unchanged(tmp_path):
    (tmp_path / "app.py").write_text("x = 1\n")
    llm = _FakeLLM(json.dumps({
        "summary": "update app",
        "files": [{"rel_path": "app.py", "op": "rewrite", "intent": "add a route"}],
    }))
    planner = make_planner_node(llm)
    state = initial_state([HumanMessage(content="add a route")], repo_id="r1", repo_root=str(tmp_path))
    result = await planner(state)
    assert result["plan"] == [{"rel_path": "app.py", "op": "rewrite", "intent": "add a route"}]
