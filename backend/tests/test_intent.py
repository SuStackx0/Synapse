"""Unit tests for agents/intent.py — mode/intent heuristic classifiers."""
import pytest

from agents.intent import (
    classify_mode, classify_mode_with_history, infer_agent_type, infer_roles,
    classify_intent, extract_anchors,
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


def test_classify_mode_write_for_implement_with_to_do_list():
    # Regression: "list" was a bare _READ_CUES substring, so "to-do list"
    # flipped an obvious write request ("implement a feature ... to their
    # to-do list ...") into a 2-2 tie that the tiebreak resolved to "read".
    msg = (
        "i need to implement a feature when someone adds something to their "
        "to-do list i want them to add priority whether its high low or medium"
    )
    mode, _ = classify_mode(msg)
    assert mode == "write"


def test_classify_mode_list_all_still_reads():
    mode, _ = classify_mode("list all API endpoints")
    assert mode == "read"


# ── classify_mode_with_history ──────────────────────────────────────────

def test_classify_mode_with_history_inherits_write_for_zero_signal_reply():
    prior = ["implement rate limiting on the login endpoint"]
    mode, decided_by = classify_mode_with_history("yes please do it", prior)
    assert mode == "write"
    assert decided_by == "inherited"


def test_classify_mode_with_history_inherits_across_a_filename_reply():
    prior = ["implement rate limiting on the login endpoint"]
    mode, decided_by = classify_mode_with_history("body app.py", prior)
    assert mode == "write"
    assert decided_by == "inherited"


def test_classify_mode_with_history_does_not_override_clear_signal():
    prior = ["implement rate limiting on the login endpoint"]
    mode, decided_by = classify_mode_with_history("what does this function do?", prior)
    assert mode == "read"
    assert decided_by == "heuristic"


def test_classify_mode_with_history_no_prior_falls_back_to_default():
    mode, decided_by = classify_mode_with_history("yes please do it", [])
    assert decided_by == "default"


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
