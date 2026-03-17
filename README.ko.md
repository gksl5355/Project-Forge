[English](README.md) | [한국어](README.ko.md)

# Project Forge

**코딩 에이전트가 실수에서 배우게 만드는 도구.**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-846_passed-brightgreen?logo=pytest&logoColor=white)](#수치)
[![Dependencies](https://img.shields.io/badge/deps-2_(typer%2C_pyyaml)-blue)](#기술-스택)
[![Schema](https://img.shields.io/badge/schema-v4-orange)](#실험-추적)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/gksl5355/Project-Forge?style=flat&logo=github)](https://github.com/gksl5355/Project-Forge)

---

Claude Code를 쓸 때 같은 실수가 반복되거나, 지난번에 찾은 해결법을 다시 잊어버린 적 있나요? Forge는 세션마다 발생한 실패/결정/규칙을 자동으로 기억하고, 다음 세션에서 관련 경험을 주입합니다.

## 어떻게 동작하나?

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

**한 번 설치하면 신경 안 써도 됩니다.** Claude Code hooks로 자동 실행됩니다.

## 설치 (2줄)

```bash
pip install git+https://github.com/gksl5355/Project-Forge.git
forge setup
```

`forge setup`은 뭐가 바뀌는지 먼저 보여주고 확인을 받습니다:

```
=== Forge Setup ===

Hooks & Settings:
  + hooks.SessionStart: resume.sh
  = hooks.PostToolUse: detect.sh (already set)   ← 기존 값 유지
  ! env.AGENT_TEAMS = 0 (Forge recommends: 1)    ← 다르면 경고만

Skills:
  + ~/.claude/skills/spawn-team/

설치하시겠습니까? [Y/n]:
```

- `+` 추가 / `=` 이미 정상 / `!` 값이 다름 (경고만, 덮어쓰지 않음)
- `settings.json.bak` 자동 백업
- `forge setup -y`로 확인 없이 설치

## 설치되는 것

| 항목 | 위치 | 설명 |
|------|------|------|
| 경험 DB | `~/.forge/forge.db` | SQLite. 실패/결정/규칙/실험 저장 |
| 학습 hooks | `~/.forge/hooks/*.sh` | 세션 시작/종료/실패 감지 |
| 팀 스킬 4종 | `~/.claude/skills/` | spawn-team, doctor, debate, ralph |
| 모델 라우터 | `~/.forge/hooks/teammate.sh` | 에이전트별 모델 선택 |
| 설정 패치 | `~/.claude/settings.json` | hooks + env (append-only) |

## Q값 학습

[MemRL](https://arxiv.org/html/2601.03192v2) 기반 EMA:

```
Q ← Q + 0.1 × (reward - Q)

reward = 1.0 → 경고했더니 실패 안 남 (도움됨)
reward = 0.0 → 경고했는데 또 실패함 (도움 안 됨)

시간 감쇠: Q *= (1 - 0.005)^days
```

Q가 높은 경험이 먼저 주입됩니다. 낮은 건 자연히 사라집니다.

| 초기 Q | 분류 | 의미 |
|--------|------|------|
| 0.6 | near_miss | 거의 맞출 뻔한 실수 |
| 0.5 | preventable | 예방 가능한 실수 |
| 0.3 | environmental | 환경 문제 |

## 실험 추적

세션마다 config hash, document hash, unified fitness를 기록합니다:

```bash
forge measure                          # 현재 메트릭
forge trend -n 20                      # fitness 추이
forge research --max-rounds 50         # config 자동 최적화
forge research --include-docs          # 문서 분석까지 포함
```

## 팀 개발

```bash
forge recommend --complexity MEDIUM    # 팀 구성 추천
# → sonnet:2+haiku:1 (3 runs, success: 85%, confidence: medium)

forge resume --team-brief              # 팀 경험 주입
```

`/spawn-team` 스킬이 자동으로 호출합니다.

## 명령어

| 명령 | 설명 |
|------|------|
| `forge setup` | 전체 설정 (DB + hooks + skills) |
| `forge record failure` | 실패 패턴 기록 |
| `forge record decision` | 결정 기록 |
| `forge record rule` | 규칙 기록 (block/warn/log) |
| `forge list` | 목록 조회 |
| `forge detail PATTERN` | 상세 조회 |
| `forge search -t TAG` | 태그 검색 |
| `forge stats` | 통계 |
| `forge measure` | 메트릭 측정 + unified fitness |
| `forge trend` | fitness 추이 |
| `forge optimize` | config 자동 최적화 |
| `forge research` | 확장 AutoResearch |
| `forge recommend` | 팀 구성 추천 |
| `forge decay` | 시간 감쇠 적용 |
| `forge promote ID` | 전역/지식 승격 |
| `forge ingest` | 팀 런 데이터 수집 |
| `forge dedup` | 중복 패턴 병합 |

## 설정

`~/.forge/config.yml` (전부 선택사항):

```yaml
l0_max_entries: 50          # 주입할 최대 패턴 수
forge_context_tokens: 2500  # 컨텍스트 토큰 예산
alpha: 0.1                  # EMA 학습률
decay_daily: 0.005          # 일일 감쇠율
routing_n_parallel_min: 3   # 팀 스폰 최소 병렬 수
routing_n_files_min: 5      # 팀 스폰 최소 파일 수
max_agents: 5               # 에이전트 상한
```

## 수치

| 항목 | 값 |
|------|-----|
| 테스트 | 846개 (전체 통과) |
| 소스 모듈 | 32개 |
| 테스트 파일 | 32개 |
| 코드 라인 | ~10,700줄 |
| DB 스키마 | v4 |
| 외부 의존성 | 2개 (typer, pyyaml) |
| Python | 3.12+ |

## 기술 스택

- **Python 3.12+** — 런타임
- **SQLite** — 내장 DB (외부 서버 불필요)
- **Typer** — CLI 프레임워크 (명령어 파싱, 도움말 생성)
- **PyYAML** — 설정 파일 파싱

## Acknowledgements

Forge의 설계에 영감을 준 프로젝트들:

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — EMA 기반 Q값 업데이트. 핵심 발견: Q는 "실패의 심각도"가 아니라 "힌트의 유용성"을 측정
- **[OpenViking](https://github.com/nicepkg/OpenViking) (ByteDance)** — L0/L1/L2 계층 컨텍스트 로딩으로 토큰 효율 극대화
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Hook 시스템 (SessionStart/SessionEnd/PostToolUse)으로 자동 학습 가능

## License

MIT
