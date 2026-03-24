[English](README.md) | [한국어](README.ko.md)

# Forge

**어제 이미 해결한 걸 오늘 또 디버깅하지 마세요.**

[![PyPI](https://img.shields.io/pypi/v/forge-memory?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/forge-memory/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1100%2B_passed-brightgreen?logo=pytest&logoColor=white)](#기술-상세)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 문제

Claude Code 세션은 매번 백지에서 시작합니다. 어제 `--no-verify`가 파이프라인을 망가뜨렸던 것도, async 핸들러에 특정 패턴이 필요하다는 것도 기억 못 합니다. 이미 해결한 문제를 다시 수정하느라 시간과 토큰을 낭비하게 됩니다.

## Forge가 하는 일

Forge는 코딩 에이전트에게 **장기 기억**을 줍니다.

한 번 설치하면 매 세션의 실패와 해결법을 조용히 기억하고, 그 경험이 실제로 도움이 됐는지 학습(강화학습)한 다음, 다음 세션에서 같은 실수를 하기 전에 가장 유용한 경험을 주입합니다.

다음 세션에서 Forge가 이렇게 말합니다: *"지난번에 이 에러 났을 때 async context manager로 해결했어 (Q:0.8)"* — 같은 삽질을 반복하기 전에.

## 왜 Forge를 쓰나

| Forge 없이 | Forge와 함께 |
|------------|--------------|
| 에이전트가 세션마다 같은 에러 반복 | 에러 발생 전에 미리 경고 |
| 같은 수정을 매번 직접 해줘야 함 | 수정 방법이 자동으로 기억되고 주입됨 |
| 컨텍스트가 시행착오에 낭비됨 | 검증된 경험만 주입해서 토큰 절약 |
| API 키 유출 방지가 없음 | 시크릿 자동 감지, 커밋 전에 차단 |
| 프로젝트별로 따로 학습 | 패턴이 자동으로 프로젝트 간 공유 |

### Forge vs. CLAUDE.md

**둘 다 쓰세요.** 해결하는 문제가 다릅니다:

| | Forge | CLAUDE.md |
|---|---|---|
| **저장하는 것** | 세션에서 학습한 동적 패턴 | 직접 작성하는 정적 규칙 |
| **예시** | "최근 3세션에서 이 async 패턴이 타임아웃 냈음" | "DB 커넥션에는 항상 `async with` 사용" |
| **관리** | 자동 — 알아서 학습하고 잊음 | 수동 — 직접 편집 |
| **범위** | 프로젝트 간 (글로벌 승격) | 단일 프로젝트 |
| **적합한 용도** | 세션별 실패, 엣지 케이스, 뉘앙스 | 아키텍처 결정, 프로젝트 컨벤션 |

CLAUDE.md가 규칙을 정합니다. Forge는 그 규칙이 미처 다루지 못한 예외를 처리합니다.

## 설치

### 1. 설치

```bash
pip install forge-memory
```

또는 uv (더 빠름):

```bash
uv tool install forge-memory
```

> `forge` 명령어가 시스템 PATH에 있어야 합니다. `uv tool install`은 자동으로 처리됩니다. `pip`을 쓸 경우 전역 설치하세요 (virtualenv 안에서만 설치하면 안 됩니다).

### 2. 셋업

```bash
forge setup
```

30초 정도 걸립니다. 경험 데이터베이스, 세션 hooks, 가드 hooks, 팀 스킬을 설정합니다. 뭐가 바뀌는지 보여주고 확인을 받습니다.

### 3. 확인

```bash
forge stats
```

`0 failures, 0 sessions`이 보이면 준비 완료. 평소처럼 코딩 시작하세요.

### 앞으로 이렇게 됩니다

Forge는 실제 세션 데이터가 필요합니다:

- **세션 1-3**: Forge가 학습 중. 패턴이 조용히 쌓입니다.
- **세션 4-5**: 첫 경고가 나타납니다. 관련 경험 주입이 시작됩니다.
- **세션 6+**: 경고가 점점 정확해집니다. Forge Score가 올라갑니다.

의도된 설계입니다 — 노이즈를 주입하지 않기 위해서. 몇 세션 후 `forge score`로 진행 상황을 확인하세요.

## Forge Score

Forge가 얼마나 잘 작동하는지 하나의 숫자로:

```
$ forge score

=== Forge Score (workspace: default) ===

  Forge Score:     0.68 / 1.00

  학습 효과:             0.72
  컨텍스트 적중률:       0.65
  토큰 효율:             0.58
  패턴: 47개 | 세션: 23개
```

**점수 읽는 법**: 0.5 이상이면 Forge가 놓치는 것보다 돕는 게 많다는 뜻. 0.7 이상이면 에이전트가 과거 세션의 혜택을 적극적으로 받고 있다는 뜻. `forge score --detail`로 전체 상세를 볼 수 있습니다.

## 주요 기능

### 자동 학습
매 세션이 학습 기회입니다. 실패를 캡처하고, 경고가 도움이 됐는지 추적하고, 그에 맞게 조정합니다. 수동 태깅이나 라벨링이 필요 없습니다.

### 스마트 컨텍스트 주입
검증된 효과, 최근성, 관련성으로 경험을 순위 매긴 다음 상위만 주입합니다. 컨텍스트가 깨끗하게 유지됩니다.

### 가드 Hooks
흔한 에이전트 실패를 자동으로 방지:
- **시크릿 감지** — API 키, 토큰, 개인키가 커밋되기 전에 잡아냄
- **`--no-verify` 차단** — pre-commit hooks 우회 방지
- **세션 건강** — 세션이 너무 길어지면 `/compact` 제안

### 프로젝트 간 학습
같은 패턴이 2개 이상 프로젝트에서 나타나면 자동으로 글로벌 경험으로 승격. 학습이 프로젝트를 넘어서 전파됩니다.

### 적응형 경고 포맷
어떤 경고 포맷이 더 효과적인지 A/B 테스트하고 자동으로 최적 포맷에 수렴합니다. 설정할 필요 없습니다.

### 서킷 브레이커
세션이 실패 루프에 빠졌는지 감지하고, 토큰을 더 낭비하기 전에 개입합니다.

## 나에게 맞나?

- Claude Code를 주기적으로 사용 (주 3회 이상) — **맞습니다**
- 에이전트가 세션마다 같은 에러를 치는 게 보임 — **맞습니다**
- 같은 수정을 반복하는 걸 멈추고 싶음 — **맞습니다**
- Cursor / Copilot / 다른 에이전트 사용 — **아직 안 됩니다** (현재 Claude Code만)

## 명령어

**일상:**

```bash
forge setup              # 초기 설정 (한 번만)
forge score              # Forge Score 확인
forge score --detail     # 전체 상세
forge config             # 설정 조회
forge stats              # 워크스페이스 통계
```

**데이터 관리:**

```bash
forge list               # 전체 경험 목록
forge search -t python   # 태그 검색
forge detail PATTERN     # 상세 조회
forge record failure     # 수동으로 패턴 기록
forge promote ID         # 글로벌 승격
```

**자동 실행 (hooks 통해, 직접 호출 불필요):**

```bash
forge resume             # 세션 시작 → 경험 주입
forge detect             # 세션 중 → 실시간 경고
forge writeback          # 세션 종료 → transcript에서 학습
```

## 설정

```bash
forge config                    # 기본 설정 (10개)
forge config --advanced         # 전체 설정 (40+개)
forge config --set alpha=0.15   # 설정 변경
```

모든 설정은 선택사항입니다. 기본값은 사전 최적화되어 있습니다.

## 프라이버시

모든 데이터는 `~/.forge/forge.db`에 로컬 저장됩니다. 어디에도 전송하지 않습니다. 일반 SQLite이므로 언제든 확인, 내보내기, 삭제할 수 있습니다.

## 기술 상세

| 항목 | 값 |
|------|-----|
| 패키지 | [forge-memory](https://pypi.org/project/forge-memory/) |
| 테스트 | 1,100+개 (전체 통과) |
| 의존성 | 2개 (typer, pyyaml) |
| 데이터베이스 | SQLite (내장, 설정 불필요) |
| Python | 3.12+ |
| 라이선스 | MIT |

### 영감을 준 것들

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — Forge의 경험 순위 매기기에 사용된 Q-learning 알고리즘
- **[OpenViking](https://github.com/nicepkg/OpenViking)** — 토큰 효율을 위한 계층 컨텍스트 주입 방식에 영감
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — 자동 학습을 가능하게 하는 Hook 시스템

## License

MIT
