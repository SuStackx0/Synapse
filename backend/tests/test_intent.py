"""Unit tests for agents/intent.py — mode/intent heuristic classifiers."""
import pytest

from agents.intent import (
    classify_mode, infer_agent_type, infer_roles, classify_intent, extract_anchors,
)


# ── classify_mode ────────────────────────────────────────────────────────

def test_classify_mode_write_for_imperative_request():
    mode, _ = classify_mode("implement rate limiting on login")
    assert mode == "write"


def test_classify_mode_read_for_question():
    mode, _ = classify_mode("what does this function do?")
    assert mode == "read"


def test_classify_mode_read_for_traceback():
    tb = (
        "Traceback (most recent call last):\n"
        '  File "app.py", line 10, in <module>\n'
        "ValueError: bad input\n"
    )
    mode, _ = classify_mode(tb)
    assert mode == "read"


def test_classify_mode_read_for_explain_request():
    mode, _ = classify_mode("explain how the auth middleware works")
    assert mode == "read"


def test_classify_mode_write_for_add_endpoint():
    mode, _ = classify_mode("add a new endpoint for password reset")
    assert mode == "write"


def test_classify_mode_returns_heuristic_or_default_reason():
    _, reason = classify_mode("implement rate limiting on login")
    assert reason in ("heuristic", "default")


# ── infer_agent_type ─────────────────────────────────────────────────────

def test_infer_agent_type_debug_for_traceback():
    tb = 'Traceback (most recent call last):\n  File "x.py", line 1\nKeyError: "x"\n'
    assert infer_agent_type(tb) == "debug"


def test_infer_agent_type_debug_for_error_keywords():
    assert infer_agent_type("the login endpoint is failing with a 500") == "debug"


def test_infer_agent_type_review_for_review_keywords():
    assert infer_agent_type("please review this for security vulnerabilities") == "review"


def test_infer_agent_type_qa_default():
    assert infer_agent_type("what does the parse_file function do?") == "qa"


# ── infer_roles ──────────────────────────────────────────────────────────

def test_infer_roles_detects_auth():
    assert "AUTH" in infer_roles("how does the login token get validated")


def test_infer_roles_detects_multiple_roles():
    roles = infer_roles("the api route queries the database")
    assert "API" in roles
    assert "DB" in roles


def test_infer_roles_defaults_to_api_when_no_match():
    assert infer_roles("hello there") == ["API"]


def test_infer_roles_dedupes():
    roles = infer_roles("auth auth authentication login")
    assert roles.count("AUTH") == 1


# ── classify_intent ──────────────────────────────────────────────────────

def test_classify_intent_entrypoints():
    intent, role = classify_intent("list all routes in this app")
    assert intent == "entrypoints"
    assert role is None


def test_classify_intent_historical():
    intent, role = classify_intent("when did this function change")
    assert intent == "historical"
    assert role is None


def test_classify_intent_structural():
    intent, role = classify_intent("who calls this function")
    assert intent == "structural"
    assert role is None


def test_classify_intent_subsystem():
    intent, role = classify_intent("how does the auth system work")
    assert intent == "subsystem"
    assert role == "AUTH"


def test_classify_intent_semantic_fallback():
    intent, role = classify_intent("something vague and unrelated to any keyword")
    assert intent == "semantic"
    assert role is None


def test_classify_intent_priority_entrypoints_over_structural():
    # "list routes" matches entrypoints; must win over structural cues.
    intent, _ = classify_intent("list routes and what calls them")
    assert intent == "entrypoints"


# ── extract_anchors ──────────────────────────────────────────────────────

def test_extract_anchors_backtick_identifier():
    anchors = extract_anchors("what does `classify_mode` do?")
    assert "classify_mode" in anchors


def test_extract_anchors_snake_case_word():
    anchors = extract_anchors("check the safe_path function")
    assert "safe_path" in anchors


def test_extract_anchors_capitalized_identifier():
    anchors = extract_anchors("explain the FileWrite class")
    assert "FileWrite" in anchors


def test_extract_anchors_limits_to_six():
    msg = "`a_one` `b_two` `c_three` `d_four` `e_five` `f_six` `g_seven` `h_eight`"
    anchors = extract_anchors(msg)
    assert len(anchors) <= 6


def test_extract_anchors_empty_for_generic_text():
    anchors = extract_anchors("hi")
    assert anchors == []
