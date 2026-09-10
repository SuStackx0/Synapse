"""Unit tests for ingestion/graph_builder.py's pure detect_role() function.

detect_role() precedence (per the current implementation):
  1. API decorator match
  2. test-name / is_test flag
  3. DB imports
  4. AI imports
  5. path-based AUTH
  6. path-based CONFIG
  7. default UTIL

Regression coverage for the same-day fix: a root-level file like "auth.py"
must match the AUTH role even though the extension is glued to the last
path segment (bare split("/") previously left "auth.py" as one segment
that never equalled "auth").
"""
import pytest

from ingestion.graph_builder import detect_role


def fn(name="handler", decorators=None, is_test=False):
    return {"name": name, "decorators": decorators or [], "is_test": is_test}


# ── path-based AUTH/CONFIG regression (today's fix) ─────────────────────

def test_detect_role_root_level_auth_file():
    assert detect_role(fn("login"), "auth.py", []) == "AUTH"


def test_detect_role_nested_auth_file():
    assert detect_role(fn("get_user"), "app/auth/utils.py", []) == "AUTH"


def test_detect_role_root_level_config_file():
    assert detect_role(fn("load"), "config.py", []) == "CONFIG"


def test_detect_role_nested_config_dir():
    assert detect_role(fn("load"), "app/settings/base.py", []) == "CONFIG"


def test_detect_role_unrelated_file_defaults_util():
    assert detect_role(fn("helper"), "utils/misc.py", []) == "UTIL"


# ── precedence: API decorator wins over everything ───────────────────────

def test_detect_role_api_decorator_wins_over_auth_path():
    f = fn("login", decorators=["router.post"])
    assert detect_role(f, "auth.py", []) == "API"


def test_detect_role_api_decorator_variants():
    for deco in ["router.get", "router.post", "router.put", "router.delete",
                 "app.get", "app.post", "app.put", "app.delete",
                 "app.route", "app.websocket", "get", "post", "put", "delete"]:
        assert detect_role(fn(decorators=[deco]), "misc.py", []) == "API"


# ── precedence: test-name wins over DB/AI/path ────────────────────────────

def test_detect_role_test_name_prefix_wins_over_db_import():
    f = fn("test_query_users")
    assert detect_role(f, "db/tests.py", ["sqlalchemy"]) == "TEST"


def test_detect_role_is_test_flag_wins_over_auth_path():
    f = fn("check_login", is_test=True)
    assert detect_role(f, "auth.py", []) == "TEST"


# ── precedence: DB imports win over AI imports and path ───────────────────

def test_detect_role_db_import_wins_over_ai_import():
    f = fn("run")
    assert detect_role(f, "pipeline.py", ["sqlalchemy", "openai"]) == "DB"


def test_detect_role_db_import_wins_over_auth_path():
    f = fn("run")
    assert detect_role(f, "auth.py", ["neo4j"]) == "DB"


@pytest.mark.parametrize("imp", [
    "sqlalchemy", "neo4j", "asyncpg", "aiopg", "tortoise",
    "peewee", "alembic", "sqlite3", "motor", "pymongo",
])
def test_detect_role_db_import_variants(imp):
    assert detect_role(fn("run"), "misc.py", [f"{imp}.session"]) == "DB"


# ── precedence: AI imports win over path-based roles ──────────────────────

def test_detect_role_ai_import_wins_over_config_path():
    f = fn("embed")
    assert detect_role(f, "config.py", ["sentence_transformers"]) == "AI"


@pytest.mark.parametrize("imp", [
    "openai", "anthropic", "langchain", "langgraph", "transformers",
    "torch", "tensorflow", "sklearn", "sentence_transformers", "qdrant_client",
])
def test_detect_role_ai_import_variants(imp):
    assert detect_role(fn("run"), "misc.py", [f"{imp}.stuff"]) == "AI"


# ── AUTH path variants ─────────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "authentication.py", "app/security/checks.py", "token.py",
    "jwt.py", "auth/__init__.py", "authorization/rules.py",
])
def test_detect_role_auth_path_variants(path):
    assert detect_role(fn("run"), path, []) == "AUTH"


# ── CONFIG path variants ───────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    "settings.py", "configuration.py", "env.py", "app/config/base.py",
])
def test_detect_role_config_path_variants(path):
    assert detect_role(fn("run"), path, []) == "CONFIG"


# ── windows-style path separators ──────────────────────────────────────────

def test_detect_role_handles_backslash_paths():
    assert detect_role(fn("run"), "app\\auth\\utils.py", []) == "AUTH"
