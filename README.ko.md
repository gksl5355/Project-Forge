[English](README.md) | [한국어](README.ko.md)

# Project Forge

**코딩 에이전트를 위한 경험 메모리 레이어.**

[![CI](https://github.com/gksl5355/Project-Forge/actions/workflows/ci.yml/badge.svg)](https://github.com/gksl5355/Project-Forge/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1203_passed-brightgreen?logo=pytest&logoColor=white)](#수치)
[![Dependencies](https://img.shields.io/badge/deps-2_(typer%2C_pyyaml)-blue)](#기술-스택)
[![Schema](https://img.shields.io/badge/schema-v5-orange)](#아키텍처)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Forge란?

Forge는 코딩 에이전트 세션 사이에 위치하는 **경험 메모리 레이어**입니다. 오케스트레이터가 아니고, 하네스가 아닙니다 — 에이전트에게 없는 **장기 기억**입니다.

**문제:** LLM 코딩 에이전트(Claude Code, Cursor 등)는 매 세션을 백지에서 시작합니다. 같은 실수를 반복하고, 어제 찾은 해결법을 잊어버리고, 과거 실패에서 배우지 못합니다.

**Forge가 해결하는 방법:**

1. **기억** — 매 세션의 실패, 결정, 규칙을 자동으로 캡처
2. **학습** — 강화학습(Q-value)으로 어떤 경험이 실제로 도움됐는지 측정
3. **주입** — 다음 세션에 가장 유용한 경험을 효과가 검증된 순서로 주입

**Claude Code hooks**로 동작합니다 — 설치 후 수동 개입 제로.

```
세션 시작                   코딩 중                     세션 종료
  forge resume               forge detect                forge writeback
  ↓                          ↓                           ↓
  Q값 높은 패턴 로드          stderr → DB 매칭            transcript 파싱
  ↓                          ↓                           ↓
  컨텍스트 주입               경고: "전에도 이런 에러      Q값 업데이트
  "지난번에 이거 실패했어,     있었어, 이렇게 해봐"        실험 기록
   이렇게 해 (Q:0.8)"                                    자동 승격
```

## 설치

### 1단계: 설치

```bash
# pip
pip install forge-memory

# 또는 uv (더 빠름)
uv tool install forge-memory
```

> **중요:** `forge` 명령어가 시스템 PATH에 있어야 합니다. 가상환경 안에서만 설치하면 hooks가 동작하지 않습니다.

### 2단계: 셋업

```bash
forge setup
```

이 한 줄이:
- 경험 데이터베이스 생성 (`~/.forge/forge.db`)
- 학습 hooks 설치 (세션 시작/종료/실패 감지)
- 가드 hooks 설치 (시크릿 감지, `--no-verify` 차단)
- 팀 스킬 설치 (spawn-team, doctor, debate, ralph)
- `~/.claude/settings.json` 패치 (append-only, 백업 자동 생성)

```
=== Forge Setup ===

Hooks & Settings:
  + hooks.SessionStart: resume.sh
  + hooks.SessionEnd: writeback.sh
  + hooks.PostToolUse: detect.sh
  = env.AGENT_TEAMS = 1 (ok)           ← 기존 값 유지
  ! env.SOME_KEY = X (recommends: Y)   ← 다르면 경고만

Skills:
  + ~/.claude/skills/spawn-team/

설치하시겠습니까? [Y/n]:
```

- `forge setup -y`로 확인 없이 설치

### 3단계: 끝

코딩 시작하세요. Forge가 매 세션에서 자동으로 학습합니다.

```bash
# 몇 세션 후 Forge Score 확인
forge score

# 상세 보기
forge score --detail
```

### 개발자용 (editable 설치)

```bash
git clone https://github.com/gksl5355/Project-Forge.git
cd Project-Forge
pip install -e ".[dev]"     # 또는: make dev
forge setup
```

## 기능

### 자동 경험 학습

매 세션이 학습 → 기억 → 주입 사이클을 거칩니다:

| 단계 | Hook | 동작 |
|------|------|------|
| **시작** | `forge resume` | Q값 상위 경험 로드 → 에이전트 컨텍스트에 주입 |
| **코딩 중** | `forge detect` | stderr/실패를 기존 패턴과 매칭 → 실시간 경고 |
| **종료** | `forge writeback` | transcript 파싱 → 새 실패 추출 → Q값 업데이트 |

수동 개입 없음. 세션을 거듭할수록 Forge가 똑똑해집니다.

### Q값 학습 (MemRL)

[MemRL](https://arxiv.org/html/2601.03192v2) 기반 — 각 경험에 Q값이 있어서 실제로 얼마나 유용한지 측정합니다:

```
Q ← Q + α(reward - Q)

reward = 1.0 → 경고했더니 실패 안 남 (도움됨)
reward = 0.0 → 경고했는데 또 실패함 (도움 안 됨)

시간 감쇠: Q *= (1 - 0.005)^days
```

Q가 높은 경험이 먼저 주입됩니다. 낮은 건 자연히 사라집니다.

### Forge Score

Forge가 얼마나 잘 작동하는지 하나의 숫자로:

```bash
forge score
# === Forge Score (workspace: default) ===
#
#   Forge Score:     0.68 / 1.00
#
#   학습 효과 (QWHR):     0.72
#   컨텍스트 적중률:       0.65
#   토큰 효율:             0.58
#   패턴: 47개 | 세션: 23개

forge score --detail     # 라우팅, 브레이커 등 전체 상세
```

8개 내부 지표를 가중 합산한 점수입니다. 공식을 알 필요 없이 숫자가 올라가는지만 보면 됩니다.

### 스마트 컨텍스트 주입

경험을 한꺼번에 쏟아붓지 않습니다. 세 가지 기준으로 순위를 매깁니다:

- **Q값** — 검증된 유용성
- **최근성** — 최근 실패에 높은 가중치 (decay 설정 가능)
- **관련성** — 현재 세션 태그와의 유사도

상위 경험만 토큰 효율적 포맷으로 변환해서 세션 시작 시 주입합니다.

### 적응형 경고 포맷

어떤 경고 포맷이 에이전트에게 더 효과적인지 자동으로 A/B 테스트합니다:

- **Essential**: `[WARN] pattern → hint` (토큰 최소)
- **Annotated**: `[WARN] pattern Q:0.75 → hint` (균형)
- **Concise**: `[WARN] pattern Q:0.75 → hint_short` (기본값)
- **Detailed**: 전체 통계 포함

효과가 높은 포맷으로 자동 수렴합니다.

### 가드 Hooks

에이전트의 흔한 실패 모드를 자동으로 방지:

| Hook | 기능 |
|------|------|
| `block-no-verify.sh` | `--no-verify` 차단 — pre-commit 우회 방지 |
| `guard-secrets.sh` | API 키, 토큰, 개인키 감지 |
| `suggest-compact.sh` | 50+ 도구 호출 시 `/compact` 제안 |
| `cost-tracker.sh` | 세션 메트릭 기록 (효율 추적용) |

### 서킷 브레이커

세션이 실패 루프에 빠졌는지 자동 감지:

- 연속 실패 횟수와 총 도구 호출 수 추적
- 한계 초과 시 트립 (설정 가능)
- 성공 시 리셋

### 모델 라우팅

어떤 LLM 모델이 어떤 작업 유형에 최적인지 학습:

```
빠른 작업  → claude-haiku-4-5      (빠르고 저렴)
일반       → claude-sonnet-4-6     (균형)
깊은 분석  → claude-opus-4-6       (꼼꼼)
코드 리뷰  → claude-sonnet-4-6     (리뷰에 강함)
```

세션 데이터가 쌓일수록 라우팅 정확도가 향상됩니다.

### 팀 오케스트레이션 지원

`/spawn-team`과 연동하여 멀티 에이전트 런에서 학습:

```bash
forge recommend --complexity MEDIUM
# → sonnet:2+haiku:1 (3 runs, success: 85%, confidence: medium)

forge resume --team-brief
# → 최근 팀 실패 + 추천 구성
```

### 글로벌 승격

패턴이 2개 이상 프로젝트에서 나타나면 자동으로 글로벌 경험으로 승격 — 모든 워크스페이스에 혜택.

## 명령어

### 일상

| 명령 | 설명 |
|------|------|
| `forge setup` | 전체 설정 (DB + hooks + skills + settings) |
| `forge score` | Forge Score 조회 |
| `forge score --detail` | 전체 상세 |
| `forge config` | 설정 조회/변경 |
| `forge stats` | 워크스페이스 통계 |

### 데이터 관리

| 명령 | 설명 |
|------|------|
| `forge record failure` | 실패 패턴 기록 |
| `forge record decision` | 결정 기록 |
| `forge record rule` | 규칙 기록 (block/warn/log) |
| `forge list` | 목록 조회 |
| `forge detail PATTERN` | 상세 조회 |
| `forge search -t TAG` | 태그 검색 |
| `forge edit` | 기록 편집 |

### 분석

| 명령 | 설명 |
|------|------|
| `forge trend` | fitness 추이 |
| `forge recommend` | 팀 구성 추천 |
| `forge decay` | 시간 감쇠 적용 |
| `forge promote ID` | 전역/지식 승격 |
| `forge ingest` | 팀 런 데이터 수집 |
| `forge dedup` | 중복 패턴 병합 |

### Hooks (자동 실행, 직접 호출 불필요)

| 명령 | 트리거 | 설명 |
|------|--------|------|
| `forge resume` | SessionStart | 컨텍스트에 경험 주입 |
| `forge detect` | PostToolUse | 실시간 실패 매칭 |
| `forge writeback` | SessionEnd | 세션 transcript에서 학습 |

## 설정

```bash
forge config                    # 기본 설정 조회
forge config --set alpha=0.15   # 설정 변경
forge config --advanced         # 전체 파라미터 조회 (40+개)
```

기본 설정 (`~/.forge/config.yml`):

```yaml
max_tokens: 3000          # 주입 최대 토큰
l0_max_entries: 50         # 표시할 최대 패턴 수
llm_model: claude-haiku-4-5-20251001
alpha: 0.1                 # EMA 학습률
routing_enabled: true      # 모델 라우팅 on/off
circuit_breaker_enabled: true
```

모든 설정은 선택사항입니다. 기본값은 사전 최적화되어 있습니다.

## 아키텍처

```
forge/
├── cli.py              # Typer CLI (전체 명령어)
├── config.py           # ForgeConfig + YAML 로딩
├── engines/            # 핵심 엔진
│   ├── resume.py       # 세션 시작: 컨텍스트 주입
│   ├── detect.py       # 세션 중: 실패 매칭
│   ├── writeback.py    # 세션 종료: 학습
│   ├── fitness.py      # Forge Score 계산
│   ├── routing.py      # 모델 라우팅
│   ├── prompt_optimizer.py  # A/B 테스팅, 힌트 스코어링
│   ├── sweep.py        # 파라미터 최적화
│   └── ...
├── core/               # 핵심 로직
│   ├── qvalue.py       # Q값 EMA 업데이트
│   ├── context.py      # L0/L1 컨텍스트 포맷팅
│   ├── circuit_breaker.py
│   └── ...
├── storage/            # SQLite 저장소
│   ├── db.py           # 스키마, 커넥션
│   ├── models.py       # Dataclass 모델
│   └── queries.py      # Raw SQL 쿼리
├── hooks/              # Shell hook 템플릿
└── skills/             # 번들 SKILL.md 파일
```

**데이터 흐름:**

```
에이전트 세션
  ↓ SessionStart hook
forge resume → DB 쿼리 → 컨텍스트 주입
  ↓ PostToolUse hook (실패 시)
forge detect → 패턴 매칭 → 실시간 경고
  ↓ SessionEnd hook
forge writeback → transcript 파싱 → Q 업데이트 → 실험 기록
```

## 설치되는 것

| 항목 | 위치 | 용도 |
|------|------|------|
| 경험 DB | `~/.forge/forge.db` | SQLite — 실패, 결정, 규칙, 실험 |
| 학습 hooks | `~/.forge/hooks/*.sh` | 세션 시작/종료/실패 감지 |
| 가드 hooks | `~/.forge/hooks/*.sh` | 시크릿 감지, no-verify 차단, compact 제안 |
| 팀 스킬 | `~/.claude/skills/` | spawn-team, doctor, debate, ralph |
| 설정 패치 | `~/.claude/settings.json` | Hook 등록 (append-only, 백업 생성) |
| Config | `~/.forge/config.yml` | 선택적 오버라이드 (`forge config --set`으로 생성) |

## 수치

| 항목 | 값 |
|------|-----|
| 테스트 | 1,203개 (전체 통과) |
| 소스 모듈 | 40개 |
| 테스트 파일 | 42개 |
| 코드 라인 | ~8,900줄 |
| DB 스키마 | v5 |
| 외부 의존성 | 2개 (typer, pyyaml) |
| Python | 3.12+ |

## 기술 스택

- **Python 3.12+** — 런타임
- **SQLite** — 내장 DB, 설정 불필요, 외부 서버 없음
- **Typer** — CLI 프레임워크
- **PyYAML** — 설정 파싱

## Acknowledgements

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — EMA 기반 Q값 학습. 핵심: Q는 "실패 심각도"가 아니라 "힌트 유용성"을 측정
- **[OpenViking](https://github.com/nicepkg/OpenViking) (ByteDance)** — L0/L1/L2 계층 컨텍스트 로딩으로 토큰 효율 극대화
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Hook 시스템으로 자동 학습 가능

## License

MIT
