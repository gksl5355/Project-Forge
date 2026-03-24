[English](README.md) | [한국어](README.ko.md)

# Forge

**어제 고친 거 오늘 또 고치고 계시죠?**

[![PyPI](https://img.shields.io/pypi/v/forge-memory?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/forge-memory/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1100%2B_passed-brightgreen?logo=pytest&logoColor=white)](#기술-상세)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 이런 경험 있으시죠

Claude Code는 세션이 바뀌면 기억이 날아갑니다. 어제 `--no-verify` 때문에 파이프라인이 터졌던 것도, async 핸들러에 특정 패턴을 써야 했던 것도 까먹습니다. 결국 같은 걸 또 알려주고, 또 고치고, 토큰은 토큰대로 날립니다.

## 그래서 Forge

코딩 에이전트한테 **장기 기억**을 만들어줍니다.

한 번 깔아두면, 매 세션에서 뭘 실패했고 어떻게 고쳤는지 알아서 기록합니다. 그리고 그 경험이 진짜 도움이 됐는지 자동으로 검증합니다. 다음 세션? 같은 실수하기 전에 검증된 해결법을 먼저 알려줍니다.

이런 식입니다: *"지난번에 이 에러 났을 때 async context manager로 해결했잖아 (Q:0.8)"* — 삽질 반복하기 전에 먼저.

## 토큰 절약과 성능 개선은 어떻게?

Forge는 경험을 무차별로 쏟아붓지 않습니다. 세 가지 장치로 토큰을 아끼면서 성능을 올립니다:

**1. Q값 랭킹** — 경고를 보냈는데 실제로 도움이 됐으면 Q값이 올라가고, 무시당했으면 내려갑니다. Q값이 높은 경험만 주입하니까 컨텍스트에 쓸모없는 게 안 들어갑니다.

**2. 시간 감쇠** — 오래된 패턴은 자동으로 중요도가 내려갑니다. 3개월 전 에러를 매번 주입하느라 토큰 낭비할 일이 없습니다.

**3. A/B 포맷 테스트** — 같은 경고라도 어떻게 표현하느냐에 따라 에이전트가 따르는 비율이 다릅니다. 4가지 포맷을 자동으로 비교해서, 실제로 에이전트가 잘 따르는 포맷으로 수렴합니다.

결과적으로: **쓸모 있는 경험만, 효과 좋은 포맷으로, 최소 토큰에 주입.**

## 왜 써야 하나

### 지금 에이전트 실수를 어떻게 처리하고 있나요?

| | 아무것도 안 함 | CLAUDE.md만 씀 | **Forge** |
|---|---|---|---|
| **에러 반복** | 매번 똑같은 에러 | 규칙 잘 써놨으면 줄어듦 | 에러 나기 전에 알아서 경고 |
| **경험 관리** | 세션 끝나면 증발 | 내가 다 적어야 함 | 세션마다 자동 기록 |
| **관리 부담** | 없음 (근데 고통은 쌓임) | 규칙 하나하나 내가 관리 | 없음 — 알아서 배우고 알아서 잊음 |
| **다른 프로젝트에서도?** | 처음부터 다시 | 복붙해야 함 | 2개 이상 프로젝트에서 보이면 자동 공유 |
| **잘 되고 있는지 확인** | 방법 없음 | 방법 없음 | **Forge Score** — 8개 지표 자동 추적 |
| **시크릿 유출 방지** | 없음 | 없음 | API 키, 토큰 자동 감지 |
| **토큰 낭비** | 시행착오에 다 씀 | 규칙이 길면 매번 다 들어감 | 검증된 것만 골라서 넣음 |

### CLAUDE.md랑 같이 쓰세요

역할이 다릅니다:

| | Forge | CLAUDE.md |
|---|---|---|
| **뭘 담나** | 세션에서 자동으로 배운 것 | 내가 직접 적은 규칙 |
| **예를 들면** | "이 패턴 3번 연속 타임아웃 남" | "DB 연결엔 항상 `async with` 쓸 것" |
| **관리** | 자동 (도움 안 되면 알아서 사라짐) | 수동 (내가 고쳐야 함) |
| **범위** | 프로젝트 넘어서 자동 공유 | 이 프로젝트만 |

CLAUDE.md가 원칙을 정하고, Forge는 원칙이 커버 못 하는 실전 예외를 잡아줍니다.

### 숫자로 보면

| | |
|---|---|
| 설치 | ~30초 (`forge setup` 한 줄) |
| 의존성 | 2개뿐 (typer, pyyaml) |
| 저장소 | SQLite 파일 하나, 내 컴퓨터에만 |
| 추적하는 경험 종류 | 5가지 (실패, 결정, 규칙, 지식, 실험) |
| 세션마다 측정하는 지표 | 8개 (학습 효과, 라우팅 정확도, 토큰 효율 등) |
| 경고 포맷 | 4종 — A/B 테스트로 알아서 최적 선택 |
| 보호 기능 | 4종 (시크릿 감지, no-verify 차단, compact 제안, 비용 추적) |
| 테스트 | 1,100+개 통과 |

## 설치하기

### 1. 설치

```bash
pip install forge-memory
```

uv 쓰면 더 빠릅니다:

```bash
uv tool install forge-memory
```

> `forge` 명령어가 시스템 PATH에 잡혀야 합니다. `uv tool install`은 알아서 해주고, `pip`은 전역으로 설치해야 합니다 (가상환경 안에만 깔면 hooks가 못 찾음).

### 2. 셋업

```bash
forge setup
```

30초면 끝. 경험 DB, 학습 hooks, 보안 hooks, 팀 스킬까지 한 번에 잡아줍니다. 뭐가 바뀌는지 먼저 보여주고 확인 받습니다.

### 3. 확인

```bash
forge stats
```

`0 failures, 0 sessions` 나오면 준비 완료. 평소처럼 코딩 시작하세요.

### 그다음은?

Forge는 실제 세션을 거쳐야 배웁니다:

- **1~3세션**: 조용히 패턴 수집 중. 아직 경고 없음.
- **4~5세션**: 첫 경고가 뜸. "어, 이거 전에도 본 건데?"
- **6세션~**: 경고가 점점 정확해짐. Forge Score가 올라감.

일부러 이렇게 만들었습니다. 쓸데없는 경고로 귀찮게 하지 않으려고요.

## Forge Score

Forge가 제대로 돌아가는지 숫자 하나로 확인:

```
$ forge score

=== Forge Score (workspace: default) ===

  Forge Score:     0.68 / 1.00

  학습 효과:             0.72
  컨텍스트 적중률:       0.65
  토큰 효율:             0.58
  패턴: 47개 | 세션: 23개
```

**0.5 이상** — 놓치는 것보다 잡는 게 많음. Forge가 돌아가고 있다는 뜻.
**0.7 이상** — 에이전트가 과거 세션 덕을 확실히 보고 있음.

`forge score --detail`하면 전체 항목별로 볼 수 있습니다.

## 주요 기능

### 자동 학습
세션이 끝날 때마다 대화 기록을 분석해서 새 실패 패턴을 뽑아냅니다. 뭔가 태깅하거나 적어둘 필요 없이, 그냥 코딩만 하면 됩니다.

### 실시간 경고
코딩하다 에러가 나면 과거에 비슷한 에러가 있었는지 바로 확인합니다. 있으면 즉시 경고: "전에도 이런 적 있었고, 이렇게 해결했어."

### 보안 가드
에이전트가 흔히 저지르는 실수를 자동 차단:
- API 키, 토큰, 개인키가 코드에 들어가려 하면 잡아냄
- `--no-verify`로 pre-commit 우회하려 하면 막음
- 세션이 너무 길어지면 `/compact` 권유

### 프로젝트 간 전파
같은 패턴이 2개 이상 프로젝트에서 반복되면 자동으로 공통 경험으로 올라갑니다. A 프로젝트에서 배운 게 B 프로젝트에서도 바로 쓰입니다.

### 무한 루프 차단
에이전트가 같은 실패만 계속 반복하고 있으면 자동 감지해서, 토큰 더 태우기 전에 끊어줍니다.

## 나한테 맞나?

- Claude Code 자주 쓴다 (주 3회+) → **쓰세요**
- 에이전트가 같은 실수 반복하는 게 보인다 → **쓰세요**
- 매번 같은 걸 고쳐주는 게 지겹다 → **쓰세요**
- Cursor / Copilot 쓴다 → **아직 안 됨** (지금은 Claude Code만)

## 명령어

**매일 쓰는 것:**

```bash
forge setup              # 처음 설치할 때 한 번
forge score              # 점수 확인
forge score --detail     # 세부 항목까지
forge config             # 설정 보기
forge stats              # 통계
```

**데이터 관리:**

```bash
forge list               # 저장된 경험 전체 보기
forge search -t python   # 태그로 검색
forge detail PATTERN     # 특정 패턴 상세
forge record failure     # 수동으로 기록
forge promote ID         # 글로벌로 올리기
```

**알아서 실행됨 (건드릴 필요 없음):**

```bash
forge resume             # 세션 시작 → 경험 주입
forge detect             # 코딩 중 → 실시간 경고
forge writeback          # 세션 끝 → 배운 거 저장
```

## 설정

```bash
forge config                    # 기본 설정 (10개)
forge config --advanced         # 전체 설정 (40+개)
forge config --set alpha=0.15   # 값 바꾸기
```

다 선택사항입니다. 기본값이 이미 튜닝돼 있어서 안 건드려도 됩니다.

## 데이터는 내 컴퓨터에만

`~/.forge/forge.db` 파일 하나에 다 저장됩니다. 외부 전송 없음. 보고 싶으면 SQLite 뷰어로 열면 되고, 지우고 싶으면 파일 하나 삭제하면 끝.

## 기술 상세

| 항목 | 값 |
|------|-----|
| 패키지 | [forge-memory](https://pypi.org/project/forge-memory/) |
| 테스트 | 1,100+개 통과 |
| 의존성 | 2개 (typer, pyyaml) |
| DB | SQLite (내장, 설정 필요 없음) |
| Python | 3.12+ |
| 라이선스 | MIT |

### 만들 때 참고한 것들

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — 경험의 유용성을 측정하는 Q-learning 알고리즘
- **[OpenViking](https://github.com/nicepkg/OpenViking)** — 토큰을 아끼면서 경험을 주입하는 계층 구조 아이디어
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — 이 모든 걸 자동으로 돌릴 수 있게 해주는 Hook 시스템

## License

MIT
