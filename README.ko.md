<div align="center">

<img src=".github/assets/hero-banner.svg" alt="Forge — 코딩 에이전트를 위한 경험 학습 엔진" width="100%"/>

<br/>

[![PyPI](https://img.shields.io/pypi/v/forge-memory?style=flat-square&logo=pypi&logoColor=white)](https://pypi.org/project/forge-memory/)
[![Python](https://img.shields.io/badge/python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1243_passed-brightgreen?style=flat-square&logo=pytest&logoColor=white)](#기술-정보)
[![MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

[English](README.md) · [한국어](README.ko.md)

</div>

---

```
$ claude                              # 세션 시작

[Forge] 경험 3건 로드 (Q > 0.5)
  ⚠ async_timeout — DB 연결은 context manager로 감싸세요 (Q: 0.82)
  ⚠ missing_dotenv — config import 전에 python-dotenv 먼저 설치 (Q: 0.71)
  ℹ pytest_scope — session scope fixture는 teardown 명시 필요 (Q: 0.65)
```

## 설치

```bash
pip install forge-memory    # 또는 uv tool install forge-memory
forge setup                 # DB + hooks + skills (~30초)
forge stats                 # 확인: 0 failures, 0 sessions
```

끝입니다. 평소처럼 코딩하면 Forge가 알아서 배웁니다.

> `forge`가 PATH에 잡혀야 합니다. `uv tool install`은 자동으로 처리되고,
> `pip`은 전역 설치가 필요합니다. 가상환경 안에만 있으면 hooks가 못 찾습니다.

---

## 뭘 하는 건지

Claude Code 세션은 끝나면 전부 날아갑니다. 어제 `--no-verify`로 CI 터뜨린 것도, async 패턴이 필요했던 것도 기억 못 합니다.

Forge를 깔아두면 달라집니다. 세션마다 실패와 해결법을 자동으로 기록하고, 실제로 도움이 됐는지 강화학습(Q-value)으로 검증합니다. 다음 세션에서 같은 실수가 나오기 전에 먼저 알려줍니다.

### 원리

<img src=".github/assets/flow-diagram.svg" alt="Forge 동작 흐름도" width="100%"/>

**Q값 랭킹** — 경고가 실제로 도움이 됐으면 Q가 오르고, 무시당했으면 내려갑니다. Q가 높은 경험만 컨텍스트에 들어가니까 쓸데없는 정보가 끼어들 일이 없습니다.

**시간 감쇠** — 오래된 패턴은 자동으로 밀려납니다. 3개월 전 에러가 매번 자리 차지하는 일은 없습니다.

**A/B 포맷** — 같은 경고도 표현에 따라 에이전트 반응이 다릅니다. 4가지 포맷을 돌려보고 제일 잘 먹히는 걸로 수렴합니다.

결과: **검증된 경험만, 효과 좋은 포맷으로, 최소 토큰에 주입.**

## 비교

| | 아무것도 안 씀 | CLAUDE.md만 | **Forge** |
|---|---|---|---|
| 에러 반복 | 매 세션 | 규칙 있으면 줄어듦 | 발생 전 경고 |
| 지식 축적 | 세션 끝 = 소멸 | 직접 작성 | 자동 기록 |
| 관리 | 없음 (고통은 누적) | 규칙마다 직접 | 없음 — 자동 |
| 프로젝트 간 공유 | 불가 | 복붙 | 2개+ 프로젝트면 자동 |
| 효과 측정 | 불가 | 불가 | 8개 KPI |
| 토큰 비용 | 삽질에 소모 | 고정 (매번 전체 로드) | 검증된 것만 동적 주입 |

> **CLAUDE.md와 역할이 다릅니다.** CLAUDE.md는 원칙을 정하고, Forge는 원칙이 못 잡는 실전 예외를 처리합니다.

## Forge Score

잘 돌아가고 있는지 숫자 하나로 확인:

```
$ forge score

=== Forge Score (workspace: default) ===

  Forge Score:     0.68 / 1.00

  학습 효과:             0.72
  컨텍스트 적중률:       0.65
  토큰 효율:             0.58
  패턴: 47개 | 세션: 23개
```

**0.5 이상** = 놓치는 것보다 잡는 게 많음 · **0.7 이상** = 확실히 효과 있음

`forge score --detail`로 항목별 상세를 볼 수 있습니다.

## 기능

### 자동 학습
세션이 끝날 때마다 대화를 분석해서 실패 패턴을 추출하고 Q값을 갱신합니다. 태깅이나 메모 같은 건 필요 없습니다.

### 컨텍스트 주입
Q값 x 최신성 x 관련도 순위로 상위 경험만 넣습니다. 컨텍스트 윈도우가 깨끗하게 유지됩니다.

### 보안 가드
- **시크릿 감지** — API 키, 토큰, 개인키가 커밋되기 전에 잡아냄
- **`--no-verify` 차단** — pre-commit 우회 시도를 막음
- **세션 관리** — 세션이 길어지면 `/compact` 권유

### 프로젝트 간 학습
같은 패턴이 2개 이상 프로젝트에서 나타나면 글로벌로 자동 승격됩니다.

### 서킷 브레이커
같은 실패를 계속 반복하고 있으면 감지해서 끊어줍니다. 토큰 낭비 방지.

## 적응 기간

실제 세션이 쌓여야 동작합니다:

- **1~3세션**: 패턴 수집 중. 경고 없음.
- **4~5세션**: 첫 경고 시작.
- **6세션~**: 정확도 상승. Score가 오릅니다.

## 명령어

```bash
# 기본
forge setup                  # 최초 설치
forge score                  # 점수 확인
forge score --detail         # 항목별 상세
forge config                 # 설정 보기
forge stats                  # 통계

# 데이터
forge list                   # 전체 경험 목록
forge search -t python       # 태그 검색
forge detail PATTERN         # 패턴 상세
forge record failure         # 수동 기록
forge promote ID             # 글로벌 승격

# 자동 (hooks가 실행, 직접 호출할 일 없음)
forge resume                 # 세션 시작 → 경험 주입
forge detect                 # 코딩 중 → 실시간 경고
forge writeback              # 세션 종료 → 학습
```

## 설정

```bash
forge config                       # 기본 10개
forge config --advanced            # 전체 40+개
forge config --set alpha=0.15      # 값 변경
```

기본값이 이미 최적화되어 있어서 건드리지 않아도 됩니다.

## 프라이버시

모든 데이터는 `~/.forge/forge.db`에 저장됩니다. 외부 전송 없음. SQLite 파일이라 직접 열어볼 수 있고, 지우면 완전히 사라집니다.

## 기술 정보

| | |
|---|---|
| 패키지 | [forge-memory](https://pypi.org/project/forge-memory/) |
| 테스트 | 1,243 통과 |
| 의존성 | 2개 (typer, pyyaml) |
| DB | SQLite (내장) |
| Python | 3.12+ |
| 라이선스 | MIT |

### 참고

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — Q-learning 기반 경험 랭킹
- **[OpenViking](https://github.com/nicepkg/OpenViking)** — 계층적 컨텍스트 주입
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — 자동 학습을 가능하게 하는 Hook 시스템

## License

MIT
