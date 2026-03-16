"""Tests for forge.core.matcher."""

import pytest

from forge.core.matcher import extract_errors_from_stderr, match_pattern, suggest_pattern_name
from forge.storage.models import Failure


def _make_failure(pattern: str, q: float = 0.5) -> Failure:
    return Failure(
        workspace_id="test",
        pattern=pattern,
        avoid_hint="hint",
        hint_quality="near_miss",
        q=q,
    )


# --- extract_errors_from_stderr ---

def test_extract_connection_error():
    stderr = "Traceback (most recent call last):\n  ...\nConnectionError: timed out"
    errors = extract_errors_from_stderr(stderr)
    assert "connection_error" in errors


def test_extract_value_error():
    errors = extract_errors_from_stderr("ValueError: invalid literal for int()")
    assert "value_error" in errors


def test_extract_module_not_found():
    errors = extract_errors_from_stderr("ModuleNotFoundError: No module named 'requests'")
    assert "missing_module_requests" in errors


def test_extract_import_error():
    errors = extract_errors_from_stderr("ImportError: No module named 'yaml'")
    assert "missing_module_yaml" in errors


def test_extract_module_not_found_takes_priority_over_class():
    # ModuleNotFoundError는 missing_module_X로 먼저 추출됨
    errors = extract_errors_from_stderr("ModuleNotFoundError: No module named 'pandas'")
    assert "missing_module_pandas" in errors


def test_extract_multiple_errors():
    stderr = "ValueError: bad\nConnectionError: timeout"
    errors = extract_errors_from_stderr(stderr)
    assert "value_error" in errors
    assert "connection_error" in errors


def test_extract_empty_stderr():
    assert extract_errors_from_stderr("") == []


def test_extract_no_errors_in_text():
    assert extract_errors_from_stderr("just some plain text output") == []


def test_extract_dotted_module_name():
    errors = extract_errors_from_stderr("ModuleNotFoundError: No module named 'forge.core'")
    assert "missing_module_forge_core" in errors


# --- suggest_pattern_name ---

def test_suggest_module_not_found():
    assert suggest_pattern_name("ModuleNotFoundError: No module named 'pandas'") == "missing_module_pandas"


def test_suggest_import_error():
    assert suggest_pattern_name("ImportError: No module named 'yaml'") == "missing_module_yaml"


def test_suggest_error_class():
    assert suggest_pattern_name("ValueError: invalid literal") == "value_error"


def test_suggest_connection_error():
    assert suggest_pattern_name("ConnectionError: refused") == "connection_error"


def test_suggest_empty_returns_unknown():
    assert suggest_pattern_name("") == "unknown_error"


def test_suggest_whitespace_only_returns_unknown():
    assert suggest_pattern_name("   ") == "unknown_error"


def test_suggest_general_text():
    result = suggest_pattern_name("some random failure happened here")
    assert result  # 비어 있지 않아야 함
    assert " " not in result  # 공백 없음
    assert result == result.lower()  # 소문자


def test_suggest_max_length():
    long_stderr = "x" * 200
    result = suggest_pattern_name(long_stderr)
    assert len(result) <= 50


# --- match_pattern ---

def test_match_pattern_found():
    failures = [_make_failure("connection_error"), _make_failure("value_error")]
    result = match_pattern("ConnectionError: refused", failures)
    assert result is not None
    assert result.pattern == "connection_error"


def test_match_pattern_not_found():
    failures = [_make_failure("value_error")]
    result = match_pattern("ConnectionError: refused", failures)
    assert result is None


def test_match_pattern_empty_list():
    assert match_pattern("ConnectionError: refused", []) is None


def test_match_pattern_empty_stderr():
    failures = [_make_failure("connection_error")]
    assert match_pattern("", failures) is None


def test_match_pattern_module_not_found():
    failures = [_make_failure("missing_module_requests")]
    result = match_pattern("ModuleNotFoundError: No module named 'requests'", failures)
    assert result is not None
    assert result.pattern == "missing_module_requests"


def test_match_pattern_returns_first_match():
    # 여러 매칭 시 첫 번째 반환
    failures = [_make_failure("value_error", q=0.3), _make_failure("connection_error", q=0.9)]
    result = match_pattern("ValueError: bad\nConnectionError: timeout", failures)
    assert result is not None
