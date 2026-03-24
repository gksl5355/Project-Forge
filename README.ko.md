[English](README.md) | [한국어](README.ko.md)

# Forge

**코딩 에이전트가 같은 실수를 반복합니다. Forge가 그걸 고칩니다.**

[![PyPI](https://img.shields.io/pypi/v/forge-memory?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/forge-memory/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-1203_passed-brightgreen?logo=pytest&logoColor=white)](#기술-상세)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## 문제

Claude Code 세션을 새로 시작할 때마다 에이전트는 백지에서 시작합니다. 어제 `--no-verify`가 파이프라인을 망가뜨렸던 것도, async 핸들러에 특정 패턴이 필요하다는 것도 기억 못 합니다. 결국 같은 수정을 반복하면서 시간과 토큰을 낭비하게 됩니다.

## Forge가 하는 일

Forge는 코딩 에이전트를 위한 **경험 메모리 레이어**입니다. 한 번 설치하면 조용히:

- 매 세션의 실패, 결정, 해결법을 **기억**합니다
- 그 경험들이 실제로 도움이 됐는지 **학습**합니다 (강화학습)
- 다음 세션에서 같은 실수를 하기 전에 가장 유용한 경험을 **주입**합니다

코딩 에이전트에게 없는 **장기 기억**이라고 생각하면 됩니다.

## 왜 Forge를 쓰나

| Forge 없이 | Forge와 함께 |
|------------|--------------|
| 에이전트가 세션마다 같은 에러 반복 | 에러 발생 전에 미리 경고 |
| 같은 수정을 매번 직접 해줘야 함 | 수정 방법이 자동으로 기억되고 주입됨 |
| 컨텍스트 창이 시행착오에 낭비됨 | 검증된 경험만 주입해서 토큰 절약 |
| 에이전트가 개선되는지 알 수 없음 | **Forge Score**로 학습 효과 측정 |
| 보안 체크를 수동으로 설정해야 함 | 시크릿 감지, `--no-verify` 차단 내장 |
| 프로젝트별로 따로 학습 | 패턴이 자동으로 프로젝트 간 공유 |

## 설치 (3단계)

### 1. 설치

```bash
pip install forge-memory
```

또는 uv (더 빠름):

```bash
uv tool install forge-memory
```

### 2. 셋업

```bash
forge setup
```

이 한 줄이 모든 걸 설정합니다:
- 경험 데이터베이스
- 세션 hooks (매 세션 자동 학습)
- 가드 hooks (시크릿 감지, 안전 체크)
- 팀 스킬

뭐가 바뀌는지 보여주고 확인을 받습니다.

### 3. 끝

그게 전부입니다. 코딩 시작하세요. Forge가 백그라운드에서 자동으로 동작합니다.

몇 세션 후 점수를 확인하세요:

```bash
forge score
```

## 동작 방식

```
  Claude Code 세션 시작
            |
            v
  [forge resume] 관련 과거 경험 로드
  "지난번에 이 에러 났을 때 이렇게 해결했어 (Q:0.8)"
            |
            v
  코딩 중. 에이전트가 익숙한 에러 패턴에 도달
            |
            v
  [forge detect] 실시간 경고
  "이거 전에도 봤어 — async with를 써봐"
            |
            v
  세션 종료
            |
            v
  [forge writeback] 세션에서 학습
  - 새 패턴 캡처
  - Q값 업데이트 (경고가 도움이 됐나?)
  - 유용한 패턴을 다른 프로젝트로 승격
```

전부 **Claude Code hooks**를 통해 자동으로 동작합니다.

## Forge Score

Forge가 얼마나 잘 작동하는지 하나의 숫자로:

```bash
$ forge score

=== Forge Score (workspace: default) ===

  Forge Score:     0.68 / 1.00

  학습 효과:             0.72
  컨텍스트 적중률:       0.65
  토큰 효율:             0.58
  패턴: 47개 | 세션: 23개
```

Forge가 에이전트에게 실제로 도움이 되는 걸 학습할수록 점수가 올라갑니다. `forge score --detail`로 전체 상세를 볼 수 있습니다.

## 주요 기능

### 자동 학습
매 세션이 학습 기회입니다. 실패를 캡처하고, 경고가 도움이 됐는지 추적하고, 그에 맞게 조정합니다. 수동 태깅이나 라벨링이 필요 없습니다.

### 스마트 주입
아는 걸 전부 컨텍스트에 쏟아붓지 않습니다. 경험을 순위 매겨서:
- **검증된 효과** — 이 경고가 지난번에 실제로 에러를 막았나?
- **최근성** — 최근 실패에 높은 가중치
- **관련성** — 현재 세션 태그와의 유사도

상위 경험만 주입해서 토큰을 절약합니다.

### 가드 Hooks
흔한 에이전트 실패 모드를 자동으로 방지:
- **시크릿 감지** — API 키, 토큰, 개인키가 커밋되기 전에 잡아냄
- **`--no-verify` 차단** — 에이전트가 pre-commit hooks를 우회하는 것을 방지
- **세션 건강** — 세션이 너무 길어지면 `/compact` 제안

### 프로젝트 간 학습
같은 패턴이 2개 이상 프로젝트에서 나타나면 자동으로 글로벌 경험으로 승격합니다. 학습이 프로젝트를 넘어서 전파됩니다.

### 적응형 경고 포맷
어떤 경고 포맷이 더 효과적인지 A/B 테스트하고 자동으로 최적 포맷에 수렴합니다. 설정할 필요 없습니다.

### 서킷 브레이커
세션이 실패 루프에 빠졌는지 감지하고, 토큰을 더 낭비하기 전에 개입합니다.

## 주의사항

### 요구사항
- **Python 3.12+**
- **Claude Code** — Forge는 Claude Code의 hook 시스템을 사용합니다. 다른 에이전트는 아직 미지원.
- `forge` 명령어가 **시스템 PATH**에 있어야 합니다 (virtualenv 안에서만 설치하면 안 됨)

### 처음 몇 세션
Forge는 지식 제로에서 시작합니다. 유용한 패턴을 축적하려면 몇 세션이 필요합니다. 첫날부터 개선을 기대하지 마세요 — 5~10세션 후에 `forge score`를 확인하세요.

### Forge가 아닌 것
- **오케스트레이터가 아닙니다** — 에이전트를 제어하지 않습니다. 조언합니다.
- **테스트 러너가 아닙니다** — 테스트 스위트가 아닌 실제 코딩 세션에서 학습합니다.
- **CLAUDE.md 대체재가 아닙니다** — Forge는 동적인 세션별 학습을 담당합니다. 정적인 프로젝트 규칙은 여전히 CLAUDE.md에 두세요.

### 프라이버시
모든 데이터는 `~/.forge/forge.db`에 로컬 저장됩니다. 어디에도 전송하지 않습니다. 데이터베이스는 일반 SQLite이므로 언제든 확인, 내보내기, 삭제할 수 있습니다.

## 명령어

일상 명령어:

```bash
forge setup              # 초기 설정 (한 번만)
forge score              # Forge Score 확인
forge score --detail     # 전체 상세
forge config             # 설정 조회
forge config --set KEY=VALUE  # 설정 변경
forge stats              # 워크스페이스 통계
```

데이터 관리:

```bash
forge list               # 전체 경험 목록
forge search -t python   # 태그 검색
forge detail PATTERN     # 상세 조회
forge record failure     # 수동으로 패턴 기록
forge promote ID         # 글로벌 승격
```

자동 실행 (hooks, 직접 호출 불필요):

```bash
forge resume             # 세션 시작: 경험 주입
forge detect             # 세션 중: 실시간 경고
forge writeback          # 세션 종료: transcript에서 학습
```

## 설정

```bash
forge config             # 기본 설정 (10개)
forge config --advanced  # 전체 설정 (40+개)
```

모든 설정은 선택사항입니다. 기본값은 사전 최적화되어 있습니다. 자주 쓰는 것:

```yaml
# ~/.forge/config.yml
max_tokens: 3000          # 컨텍스트 주입 최대 토큰
l0_max_entries: 50         # 주입할 최대 패턴 수
alpha: 0.1                 # 학습률 (높을수록 빠르게 적응)
routing_enabled: true      # 모델 라우팅 on/off
```

## 기술 상세

| 항목 | 값 |
|------|-----|
| 패키지 | [forge-memory](https://pypi.org/project/forge-memory/) |
| 테스트 | 1,203개 (전체 통과) |
| 의존성 | 2개 (typer, pyyaml) |
| 데이터베이스 | SQLite (내장, 설정 불필요) |
| Python | 3.12+ |
| 라이선스 | MIT |

### 참고 자료

- **[MemRL](https://arxiv.org/html/2601.03192v2)** — Q값 학습 알고리즘
- **[OpenViking](https://github.com/nicepkg/OpenViking)** — 계층 컨텍스트 로딩
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — Hook 시스템

## License

MIT
