"""Pattern Matcher (P1): stderr → 패턴 매칭/제안."""

from __future__ import annotations

import re

from forge.storage.models import Failure

# Python 예외 클래스명 추출용 패턴
_ERROR_CLASS_RE = re.compile(
    r'\b([A-Z][a-zA-Z]*(?:Error|Exception|Warning|Fault|Interrupt))\b'
)
_MODULE_NOT_FOUND_RE = re.compile(
    r"ModuleNotFoundError: No module named '([^']+)'"
)
_IMPORT_ERROR_RE = re.compile(
    r"ImportError: No module named '([^']+)'"
)


def extract_errors_from_stderr(stderr: str) -> list[str]:
    """stderr에서 에러 클래스/메시지 추출 (regex)."""
    results: list[str] = []

    for m in _MODULE_NOT_FOUND_RE.finditer(stderr):
        results.append(f"missing_module_{m.group(1).replace('.', '_')}")

    for m in _IMPORT_ERROR_RE.finditer(stderr):
        candidate = f"missing_module_{m.group(1).replace('.', '_')}"
        if candidate not in results:
            results.append(candidate)

    for m in _ERROR_CLASS_RE.finditer(stderr):
        snake = _to_snake_case(m.group(1))
        if snake not in results:
            results.append(snake)

    return results


def suggest_pattern_name(stderr: str) -> str:
    """stderr에서 패턴명 자동 제안.

    우선순위:
    1. ModuleNotFoundError → missing_module_X
    2. 에러 클래스명 → snake_case
    3. 첫 줄 정규화 → snake_case
    """
    if not stderr.strip():
        return "unknown_error"

    m = _MODULE_NOT_FOUND_RE.search(stderr)
    if m:
        return f"missing_module_{m.group(1).replace('.', '_')}"

    m = _IMPORT_ERROR_RE.search(stderr)
    if m:
        return f"missing_module_{m.group(1).replace('.', '_')}"

    m = _ERROR_CLASS_RE.search(stderr)
    if m:
        return _to_snake_case(m.group(1))

    first_line = stderr.strip().splitlines()[0]
    return _normalize_to_snake(first_line)


def match_pattern(stderr: str, failures: list[Failure]) -> Failure | None:
    """stderr를 기존 패턴 목록과 exact match."""
    if not failures:
        return None

    extracted = extract_errors_from_stderr(stderr)
    for failure in failures:
        if failure.pattern in extracted:
            return failure

    # 패턴명 제안으로 추가 시도
    suggested = suggest_pattern_name(stderr)
    for failure in failures:
        if failure.pattern == suggested:
            return failure

    return None


def _to_snake_case(name: str) -> str:
    """CamelCase → snake_case 변환."""
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    s = re.sub(r'([a-z\d])([A-Z])', r'\1_\2', s)
    return s.lower()


def _normalize_to_snake(text: str) -> str:
    """일반 텍스트 → snake_case 정규화 (최대 50자)."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9]+', '_', text)
    text = text.strip('_')
    return text[:50] if text else "unknown_error"
