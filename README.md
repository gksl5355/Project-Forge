# Project Forge

**코딩 에이전트가 실수에서 배우게 만드는 도구.**

Claude Code를 쓸 때 같은 실수가 반복되거나, 지난번에 찾은 해결법을 다시 잊어버린 적 있나요? Forge는 세션마다 발생한 실패/결정/규칙을 자동으로 기억하고, 다음 세션에서 관련 경험을 주입해줍니다.

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![Tests](https://img.shields.io/badge/tests-846_passed-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-32_modules-blue)
![Schema](https://img.shields.io/badge/schema-v4-orange)
![LOC](https://img.shields.io/badge/LOC-10.7k-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## 이게 뭔데?

Forge는 Claude Code에 **경험 학습**을 추가하는 도구입니다.

```
세션 시작 → Forge가 과거 경험 주입 (이전에 이런 실수 했었어)
코딩 중   → 같은 실수하면 즉시 경고 (이거 전에도 했는데, 이렇게 해)
세션 끝   → 이번 세션에서 배운 것 자동 저장
```

설치하면 **아무것도 안 해도 자동으로 돌아갑니다**. 수동 기록도 가능합니다.

## 설치 (2줄)

```bash
pip install git+https://github.com/gksl5355/Project-Forge.git
forge setup
```

`forge setup`이 한 번에 모든 걸 설정합니다:

| 설치되는 것 | 위치 | 설명 |
|------------|------|------|
| 경험 데이터베이스 | `~/.forge/forge.db` | SQLite. 실패/결정/규칙/실험 저장 |
| 자동 학습 hooks | `~/.forge/hooks/*.sh` | 세션 시작/종료/실패 감지 |
| 팀 스킬 4종 | `~/.claude/skills/` | spawn-team, doctor, debate, ralph |
| 팀 모델 선택기 | `~/.forge/hooks/teammate.sh` | 에이전트별 모델 자동 라우팅 |
| Claude Code 설정 | `~/.claude/settings.json` | hooks + 환경변수 자동 패치 |

### 기존 설정이 있어도 괜찮나요?

**네.** `forge setup`은 먼저 뭐가 바뀌는지 보여주고, 확인을 받은 후 적용합니다.

```bash
$ forge setup

=== Forge Setup ===

다음 항목이 설치/변경됩니다:

Hooks & Settings:
  + ~/.forge/hooks/resume.sh
  + hooks.SessionStart: resume.sh
  = hooks.PostToolUse: detect.sh (already set)        ← 기존 값 유지
  ! env.AGENT_TEAMS = 0 (Forge recommends: 1)         ← 다르면 경고

Skills:
  + ~/.claude/skills/spawn-team/
  + ~/.claude/skills/doctor/

DB: ~/.forge/forge.db (create if missing)

설치하시겠습니까? [Y/n]:
```

- `+` 새로 추가 / `=` 이미 정상 / `!` 기존값과 다름 (경고만, 덮어쓰지 않음)
- 변경 전 `settings.json.bak` 자동 백업
- `forge setup -y`로 확인 없이 바로 설치 (CI/자동화용)

## 어떻게 동작하나?

```
[자동] 세션 시작
  forge resume → DB에서 Q값 높은 실패 패턴 로드 → Claude에게 주입
  "이전에 async connection을 닫지 않아서 3번 실패했어. Q: 0.8"

[자동] 코딩 중 Bash 실패
  forge detect → stderr를 DB 패턴과 매칭 → 즉시 경고
  "이 에러 전에도 봤어: 'Use async with for session scope'"

[자동] 세션 종료
  forge writeback → transcript 파싱 → Q값 업데이트 → 실험 기록
  - 경고가 도움됐으면 Q 올라감 (다음에 더 높은 우선순위)
  - 도움 안 됐으면 Q 내려감 (점점 사라짐)
```

## Q값 학습 — 어떻게 "유용한 경험"을 판단하나?

```
Q ← Q + 0.1 × (reward - Q)

reward = 1.0 → 경고했더니 실패 안 남 (도움됨)
reward = 0.0 → 경고했는데 또 실패함 (도움 안 됨)

시간이 지나면 자동 감쇠: Q *= (1 - 0.005)^days
```

| 초기 Q | 의미 |
|--------|------|
| 0.6 | near_miss — 거의 맞출 뻔한 실수 |
| 0.5 | preventable — 예방 가능한 실수 |
| 0.3 | environmental — 환경 문제 |

**Q가 높은 경험일수록 다음 세션에서 먼저 주입됩니다.**

## 수동으로도 기록할 수 있나요?

```bash
# 실패 기록
forge record failure -p "async_leak" -h "async with로 세션 닫기" -q near_miss

# 결정 기록
forge record decision --statement "FastAPI 사용" --rationale "async + 자동 docs"

# 규칙 기록
forge record rule --text "커밋 전 테스트 실행" --mode warn

# 조회
forge list --type failure --sort q     # Q값 순 정렬
forge detail async_leak                # 상세 보기
forge stats                            # 통계
```

## 팀 개발 (Agent Teams)

여러 에이전트를 동시에 돌릴 때도 경험을 공유합니다.

```bash
# 팀 구성 추천 (과거 성공률 기반)
forge recommend --complexity MEDIUM
# → sonnet:2+haiku:1 (3 runs, success: 85%, confidence: medium)

# 팀 경험 주입
forge resume --team-brief
# → 최근 3회 런 결과 + 팀 관련 실패 패턴
```

`/spawn-team` 스킬이 자동으로 `forge recommend`와 `forge resume`을 호출합니다.

## 최적화 — 설정을 자동으로 튜닝

```bash
# 현재 메트릭 측정
forge measure
#   QWHR: 0.72 | Promotion precision: 0.60 | Unified fitness: 0.6845

# fitness 추이 확인
forge trend -n 20

# 자동 최적화 (config 파라미터 탐색)
forge research --max-rounds 50

# 문서(CLAUDE.md) 분석까지 포함
forge research --include-docs
```

## 전체 명령어

| 명령 | 설명 |
|------|------|
| **설정** | |
| `forge setup` | 전체 설정 (DB + hooks + skills) |
| `forge setup --dry-run` | 변경 미리보기 |
| **기록** | |
| `forge record failure` | 실패 패턴 기록 |
| `forge record decision` | 결정 기록 |
| `forge record rule` | 규칙 기록 |
| `forge record knowledge` | 지식 기록 |
| **조회** | |
| `forge list` | 목록 조회 |
| `forge detail` | 상세 조회 |
| `forge search -t TAG` | 태그 검색 |
| `forge stats` | 통계 |
| **분석** | |
| `forge measure` | 최적화 메트릭 |
| `forge trend` | fitness 추이 |
| `forge optimize` | config 자동 최적화 |
| `forge research` | 확장 AutoResearch |
| **팀** | |
| `forge recommend` | 팀 구성 추천 |
| `forge ingest` | 팀 런 데이터 수집 |
| **관리** | |
| `forge decay` | 시간 감쇠 적용 |
| `forge promote ID` | 전역/지식 승격 |
| `forge dedup` | 중복 패턴 병합 |

## 수치

| 항목 | 값 |
|------|-----|
| 테스트 | 846개 (전체 통과) |
| 소스 모듈 | 32개 |
| 테스트 파일 | 32개 |
| 코드 라인 | ~10,700줄 |
| DB 스키마 | v4 (experiments + unified fitness) |
| 외부 의존성 | 2개 (typer, pyyaml) |
| Python | 3.12+ |

## 설정 파일

`~/.forge/config.yml` (전부 선택사항, 기본값 있음):

```yaml
# 컨텍스트 주입
l0_max_entries: 50          # 세션 시작 시 주입할 최대 패턴 수
forge_context_tokens: 2500  # 컨텍스트 토큰 예산

# 학습
alpha: 0.1                  # EMA 학습률
decay_daily: 0.005          # 일일 감쇠율

# 팀 라우팅
routing_n_parallel_min: 3   # 팀 스폰 최소 병렬 작업 수
routing_n_files_min: 5      # 팀 스폰 최소 파일 수
max_agents: 5               # 에이전트 상한
```

## 기술 스택

- **Python 3.12+** — 런타임
- **SQLite** — 내장 DB (외부 서버 불필요)
- **Typer** — CLI 프레임워크
- **PyYAML** — 설정 파일 파싱

## 문서

- [Architecture v0.2](docs/architecture/ARCHITECTURE_v0.2.md)
- [Migration Log](docs/MIGRATION_LOG.md) — summary.yml 제거 기록

---

## English

**A tool that makes coding agents learn from their mistakes.**

Forge automatically remembers failures, decisions, and rules across Claude Code sessions. It injects relevant experience at session start and warns you when repeating known mistakes.

### Install

```bash
pip install git+https://github.com/gksl5355/Project-Forge.git
forge setup              # sets up everything
forge setup --dry-run    # preview changes first
```

### How it works

1. **Session start**: Forge loads high-Q failure patterns and injects them into context
2. **During coding**: Real-time Bash failure detection warns against known patterns
3. **Session end**: Transcript parsed, Q-values updated, experiment recorded
4. **Team runs**: `forge recommend` suggests best team config from history

### Coexistence

`forge setup` uses **append-only merge** for `settings.json`. Your existing hooks, env vars, and plugins are preserved. Forge only adds its own entries. A `.bak` backup is created before any change.
