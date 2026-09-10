"""Unit tests for agents/write_tool.py — the file-write safety guard."""
import os
import pytest

from agents.write_tool import (
    safe_path, PathViolation, FileWrite, validate_write,
    apply_write, preview_write, ALLOWED_EXT, DENY_PARTS,
)


# ── safe_path ────────────────────────────────────────────────────────────

def test_safe_path_valid_relative_resolves_inside_root(tmp_path):
    root = str(tmp_path)
    result = safe_path(root, "src/app.py")
    assert result == os.path.realpath(os.path.join(root, "src/app.py"))
    assert result.startswith(os.path.realpath(root))


def test_safe_path_rejects_traversal(tmp_path):
    with pytest.raises(PathViolation):
        safe_path(str(tmp_path), "../../etc/passwd")


def test_safe_path_rejects_traversal_within_subdir(tmp_path):
    with pytest.raises(PathViolation):
        safe_path(str(tmp_path), "sub/../../outside.py")


def test_safe_path_rejects_absolute_path(tmp_path):
    with pytest.raises(PathViolation):
        safe_path(str(tmp_path), "/etc/passwd")


def test_safe_path_rejects_null_byte(tmp_path):
    with pytest.raises(PathViolation):
        safe_path(str(tmp_path), "app.py\x00.txt")


def test_safe_path_rejects_empty(tmp_path):
    with pytest.raises(PathViolation):
        safe_path(str(tmp_path), "")


@pytest.mark.parametrize("denied", sorted(DENY_PARTS))
def test_safe_path_rejects_deny_list_dirs(tmp_path, denied):
    with pytest.raises(PathViolation):
        safe_path(str(tmp_path), f"{denied}/evil.py")


def test_safe_path_rejects_disallowed_extension(tmp_path):
    with pytest.raises(PathViolation):
        safe_path(str(tmp_path), "payload.exe")


@pytest.mark.parametrize("ext", sorted(ALLOWED_EXT - {".env.example"}))
def test_safe_path_allows_allowed_extensions(tmp_path, ext):
    result = safe_path(str(tmp_path), f"file{ext}")
    assert result.endswith(f"file{ext}")


def test_safe_path_allows_extensionless_path(tmp_path):
    # No extension at all -> ext == "" which is falsy, so it's allowed through.
    result = safe_path(str(tmp_path), "Makefile")
    assert result.endswith("Makefile")


# ── validate_write / apply_write / preview_write ────────────────────────

def test_apply_write_create_succeeds(tmp_path):
    fw = FileWrite(rel_path="new_mod.py", op="create", content="x = 1\n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is True
    assert res.applied is True
    assert (tmp_path / "new_mod.py").read_text() == "x = 1\n"


def test_apply_write_create_fails_if_exists(tmp_path):
    (tmp_path / "exists.py").write_text("a = 1\n")
    fw = FileWrite(rel_path="exists.py", op="create", content="b = 2\n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is False
    assert "exists" in res.error


def test_apply_write_rewrite_succeeds(tmp_path):
    (tmp_path / "mod.py").write_text("a = 1\n")
    fw = FileWrite(rel_path="mod.py", op="rewrite", content="a = 2\nb = 3\n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is True
    assert res.applied is True
    assert (tmp_path / "mod.py").read_text() == "a = 2\nb = 3\n"
    # backup created
    assert (tmp_path / "mod.py.synapse.bak").exists()


def test_apply_write_append_succeeds(tmp_path):
    (tmp_path / "log.txt").write_text("line1\n")
    fw = FileWrite(rel_path="log.txt", op="append", content="line2\n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is True
    assert res.applied is True
    assert (tmp_path / "log.txt").read_text() == "line1\nline2\n"


def test_apply_write_rejects_syntax_invalid_python_rewrite(tmp_path):
    (tmp_path / "broken.py").write_text("a = 1\n")
    fw = FileWrite(rel_path="broken.py", op="rewrite", content="def f(:\n    pass\n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is False
    assert "syntax error" in res.error
    # file must remain untouched
    assert (tmp_path / "broken.py").read_text() == "a = 1\n"


def test_apply_write_append_python_skips_ast_check(tmp_path):
    # op == "append" is exempt from ast.parse per validate_write's condition.
    (tmp_path / "mod.py").write_text("a = 1\n")
    fw = FileWrite(rel_path="mod.py", op="append", content="this is not )( valid python\n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is True
    assert res.applied is True


def test_apply_write_rejects_truncation(tmp_path):
    original = "\n".join(f"x{i} = {i}" for i in range(40)) + "\n"
    (tmp_path / "big.py").write_text(original)
    # Collapsing to well under 50% of 40 lines.
    fw = FileWrite(rel_path="big.py", op="rewrite", content="x0 = 0\nx1 = 1\n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is False
    assert "truncation" in res.error
    assert (tmp_path / "big.py").read_text() == original


def test_apply_write_allows_rewrite_above_truncation_threshold(tmp_path):
    original = "\n".join(f"x{i} = {i}" for i in range(40)) + "\n"
    (tmp_path / "big.py").write_text(original)
    new_content = "\n".join(f"x{i} = {i}" for i in range(25)) + "\n"  # >= 50% of 40
    fw = FileWrite(rel_path="big.py", op="rewrite", content=new_content)
    res = apply_write(str(tmp_path), fw)
    assert res.ok is True
    assert res.applied is True


def test_apply_write_truncation_guard_ignored_under_20_lines(tmp_path):
    original = "\n".join(f"x{i} = {i}" for i in range(10)) + "\n"
    (tmp_path / "small.py").write_text(original)
    fw = FileWrite(rel_path="small.py", op="rewrite", content="x0 = 0\n")
    res = apply_write(str(tmp_path), fw)
    # old_n (10) < 20, so the truncation guard does not apply.
    assert res.ok is True
    assert res.applied is True


def test_apply_write_rejects_empty_content(tmp_path):
    fw = FileWrite(rel_path="empty.py", op="create", content="   \n")
    res = apply_write(str(tmp_path), fw)
    assert res.ok is False
    assert "empty" in res.error


def test_preview_write_never_touches_disk(tmp_path):
    fw = FileWrite(rel_path="preview_only.py", op="create", content="x = 1\n")
    res = preview_write(str(tmp_path), fw)
    assert res.ok is True
    assert res.applied is False
    assert not (tmp_path / "preview_only.py").exists()
    assert "+x = 1" in res.diff


def test_validate_write_path_violation_surfaces_error(tmp_path):
    fw = FileWrite(rel_path="../escape.py", op="create", content="x = 1\n")
    ok, err = validate_write(str(tmp_path), fw)
    assert ok is False
    assert "escapes repo root" in err
