"""Unit tests for agents/write_context.py's render_write_context.

Regression: the planner would create a new file (a route module, a
component, a utility) without ever wiring it into the running app - no
import, no registration, no call site - so the new code was dead on
arrival. render_write_context now explicitly tells the model which file
wires new code in and that it must plan an edit there too.
"""
from agents.write_context import WriteContext, render_write_context


def test_render_write_context_instructs_wiring_when_present():
    wc = WriteContext(
        repo_map="# repo map",
        placement_dir="app/routes",
        wiring_files=[("app.py", "from flask import Flask\napp = Flask(__name__)\n")],
    )
    rendered = render_write_context(wc)
    assert "### Wiring file — app.py" in rendered
    assert "never actually run" in rendered
    assert "app = Flask(__name__)" in rendered


def test_render_write_context_omits_wiring_section_when_absent():
    wc = WriteContext(repo_map="# repo map", placement_dir="app")
    rendered = render_write_context(wc)
    assert "Wiring file" not in rendered


def test_render_write_context_includes_exemplars_and_imports():
    wc = WriteContext(
        repo_map="# repo map",
        placement_dir="app",
        exemplars=[("app/models.py", "class User: pass\n")],
        imports_by_file={"app/models.py": ["sqlalchemy", "flask"]},
    )
    rendered = render_write_context(wc)
    assert "### Exemplar file (existing pattern to follow) — app/models.py" in rendered
    assert "available imports: sqlalchemy, flask" in rendered
    assert "class User: pass" in rendered
