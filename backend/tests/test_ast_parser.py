"""Unit tests for ingestion/ast_parser.py — Python AST parsing helpers."""
import os

from ingestion.ast_parser import parse_python_file, parse_file, walk_repo


SAMPLE_SRC = '''
import os
from typing import List


class Widget:
    """A widget."""

    def __init__(self, name):
        self.name = name

    @property
    def label(self):
        return self.name


@router.get("/widgets")
def list_widgets():
    return get_all()


def get_all():
    return []


def broken_helper(:
    pass
'''


def test_parse_python_file_extracts_functions_and_classes():
    good_src = SAMPLE_SRC.replace("def broken_helper(:\n    pass\n", "")
    parsed = parse_python_file("widgets.py", good_src)
    func_names = {f["name"] for f in parsed["functions"]}
    class_names = {c["name"] for c in parsed["classes"]}

    assert "list_widgets" in func_names
    assert "get_all" in func_names
    assert "Widget" in class_names
    assert "os" in parsed["imports"]
    assert "typing" in parsed["imports"]


def test_parse_python_file_detects_decorators():
    good_src = SAMPLE_SRC.replace("def broken_helper(:\n    pass\n", "")
    parsed = parse_python_file("widgets.py", good_src)
    list_widgets = next(f for f in parsed["functions"] if f["name"] == "list_widgets")
    assert "router.get" in list_widgets["decorators"]


def test_parse_python_file_handles_methods_and_properties():
    good_src = SAMPLE_SRC.replace("def broken_helper(:\n    pass\n", "")
    parsed = parse_python_file("widgets.py", good_src)
    method_names = {f["name"] for f in parsed["functions"] if f["is_method"]}
    assert {"__init__", "label"} <= method_names


def test_parse_python_file_syntax_error_returns_empty_structure():
    parsed = parse_python_file("broken.py", "def f(:\n    pass\n")
    assert parsed == {"functions": [], "classes": [], "imports": [], "calls": []}


def test_parse_file_reads_and_dispatches_by_extension(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text("def hello():\n    return 1\n")
    parsed = parse_file(str(path))
    assert parsed["language"] == "python"
    assert any(f["name"] == "hello" for f in parsed["functions"])
    assert parsed["content"] == "def hello():\n    return 1\n"


def test_walk_repo_parses_multiple_files(tmp_path):
    (tmp_path / "a.py").write_text(
        "def foo():\n    return bar()\n\n\ndef bar():\n    return 1\n"
    )
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "b.py").write_text(
        "class Baz:\n    def qux(self):\n        return 2\n"
    )
    # Should be skipped entirely.
    skip_dir = tmp_path / "node_modules"
    skip_dir.mkdir()
    (skip_dir / "ignored.py").write_text("def should_not_appear():\n    pass\n")

    results = walk_repo(str(tmp_path))
    rel_paths = {r["rel_path"] for r in results}

    assert "a.py" in rel_paths
    assert os.path.join("pkg", "b.py") in rel_paths
    assert not any("node_modules" in r for r in rel_paths)

    a_result = next(r for r in results if r["rel_path"] == "a.py")
    func_names = {f["name"] for f in a_result["functions"]}
    assert {"foo", "bar"} <= func_names

    b_result = next(r for r in results if r["rel_path"] == os.path.join("pkg", "b.py"))
    class_names = {c["name"] for c in b_result["classes"]}
    assert "Baz" in class_names
