"""Transcript Parser: transcript.jsonl → 실패한 Bash 결과 목록."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BashFailure:
    command: str
    exit_code: int
    stderr: str
    stdout: str


def parse_transcript(path: Path) -> list[BashFailure]:
    """transcript.jsonl → 실패한 Bash 결과 목록 (방어적 파싱).

    파일이 없으면 [] 반환. 잘못된 JSON 줄은 건너뜀.
    """
    if not path.exists():
        return []

    results: list[BashFailure] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        failure = _extract_bash_failure(obj)
        if failure is not None:
            results.append(failure)

    return results


def _extract_bash_failure(obj: dict) -> BashFailure | None:
    """단일 JSON 객체에서 BashFailure 추출. Bash 실패 아니면 None."""
    if not isinstance(obj, dict):
        return None

    # 다양한 transcript 포맷 처리
    tool_name = (
        obj.get("tool_name")
        or obj.get("tool")
        or obj.get("name")
        or ""
    )
    if isinstance(tool_name, str) and tool_name.lower() != "bash":
        return None

    # exit_code 추출 (여러 위치 시도)
    exit_code = _get_exit_code(obj)
    if exit_code is None or exit_code == 0:
        return None

    # stdout / stderr 추출
    stdout, stderr = _get_output(obj)
    command = _get_command(obj)

    return BashFailure(
        command=command,
        exit_code=exit_code,
        stderr=stderr,
        stdout=stdout,
    )


def _get_exit_code(obj: dict) -> int | None:
    """exit_code를 다양한 위치에서 찾아 반환."""
    # 직접 키
    if "exit_code" in obj:
        try:
            return int(obj["exit_code"])
        except (TypeError, ValueError):
            pass

    # result / output 하위 키
    for sub_key in ("result", "output", "content"):
        sub = obj.get(sub_key)
        if isinstance(sub, dict) and "exit_code" in sub:
            try:
                return int(sub["exit_code"])
            except (TypeError, ValueError):
                pass

    return None


def _get_output(obj: dict) -> tuple[str, str]:
    """stdout, stderr를 다양한 위치에서 추출."""
    # 직접 키
    stdout = obj.get("stdout") or ""
    stderr = obj.get("stderr") or ""
    if stdout or stderr:
        return str(stdout), str(stderr)

    # result / output 하위 키
    for sub_key in ("result", "output", "content"):
        sub = obj.get(sub_key)
        if isinstance(sub, dict):
            stdout = sub.get("stdout") or ""
            stderr = sub.get("stderr") or ""
            if stdout or stderr:
                return str(stdout), str(stderr)

    return "", ""


def _get_command(obj: dict) -> str:
    """command / cmd / input 키에서 명령 추출."""
    for key in ("command", "cmd"):
        val = obj.get(key)
        if isinstance(val, str):
            return val

    # input 하위 키
    inp = obj.get("input")
    if isinstance(inp, dict):
        val = inp.get("command") or inp.get("cmd") or ""
        if isinstance(val, str):
            return val

    return ""
