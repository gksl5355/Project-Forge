# Project Forge — 아이디어 노트

## 출발점

코딩 에이전트용 경험 학습 도구를 만들려고 시작했다.
에이전트가 세션 간에 경험을 이어가고, 같은 실수를 반복하지 않고, 왜 그런 결정을 했는지 복원할 수 있는 시스템.

## 영감을 준 것들

### MemRL (핵심 이론 기반)
- 에이전트가 경험에서 학습하는 구조화된 메모리 개념
- **메모리 삼중조**: Intent(의도) + Experience(경험) + Utility(효용) = 하나의 기억
- **EMA 기반 Q값 업데이트**: `Q ← Q + α(r - Q)` — 수렴이 수학적으로 보장됨
- **2단계 검색**: 유사도로 후보 필터 → Q값으로 최종 순위
- **핵심 발견**: 실패 기록의 ~12%가 Q값 0.9 이상 (near-miss의 avoid_hint가 가장 유용)
- **결론**: Q값은 "실패의 심각도"가 아니라 "힌트의 유용성"을 측정해야 함

### OpenViking (ByteDance)
- 에이전트용 컨텍스트 DB, 12.4k stars
- **L0/L1/L2 계층 로딩**: 컨텍스트 크기를 3단계로 관리 → 토큰 효율 극대화
  - L0 (~100 토큰): 빠른 필터링용 추상
  - L1 (~2000 토큰): 네비게이션/이해용 요약
  - L2 (무제한): 필요시만 상세 로드
- **Session Commit 모델**: 세션 종료 시 자동으로 메모리 후보 추출
- **중복 제거/병합**: 유사도 기반으로 기존 기억과 비교, 중복이면 병합

### claude-mem (실사용 검증)
- Claude Code용 SQLite + Hook 기반 메모리 확장
- **Forge 설계와 동일한 패턴**: SessionStart→resume, SessionEnd→writeback
- **L0/L1/L2 계층 로딩 실사용**: ~10배 토큰 절감 확인
- **차별점**: claude-mem은 단순 저장. Forge는 Q값 갱신 + 전역 승격 + 패턴 매칭 추가

### MemOS
- 메모리의 CRUD 모델: Add, Retrieve, Edit, Delete
- inspect/edit 가능한 구조 (블랙박스 아님)
- 피드백 루프: 자연어 피드백으로 기존 메모리 수정/보충

### MiroFish
- 상황 시뮬레이션, 예측 — "이렇게 하면 어떻게 될까"
- 패턴 매칭 → 벡터 유사도 → LLM reasoning (3단계 진화)
- Forge의 P1→P2→P3 진화 경로와 일치

### 오케스트레이터 경험
- 여태 만들어본 오케스트레이터들에서 얻은 교훈이 기반
- task lifecycle, resume, write-back 개념으로 발전

### Karpathy의 Auto Research
- 목표를 주면 알아서 리서치→실행→검증 루프를 도는 개념
- evaluation linkage, next action 추천으로 반영

---

## 핵심 thesis

> **"코딩 에이전트가 세션을 거듭할수록 같은 실수를 줄이고, 더 나은 판단을 하게 되는 시스템"**

핵심 문제:
- 세션이 끝나면 실패 경험이 휘발된다
- 같은 실수를 반복한다
- 과거 경험이 다음 의사결정에 반영되지 않는다
- 프로젝트별 규칙이 일관되게 적용되지 않는다

---

## 방향 전환 기록

### v0.1 (초기 구상)
- FastAPI + PostgreSQL + Qdrant 풀스케일 서버
- MCP 서버로 Claude Code 연동
- 도메인 중립 코어 + 어댑터 패턴

### v0.2 (현재 방향) — 2026-03-16 재정의

**왜 바꿨나:**
- Claude Code 자체 메모리가 이미 있어서, 별도 서버의 가치가 불분명
- PostgreSQL + Qdrant 서버를 띄우는 건 도입 허들이 너무 높음
- 써봐야 가치를 아는 제품인데, 써보기까지가 너무 멀었음

**바뀐 것:**

| 항목 | v0.1 | v0.2 |
|------|------|------|
| 형태 | 서버 (FastAPI) | CLI 도구 |
| 저장소 | PostgreSQL + Qdrant | SQLite (파일 하나) |
| 연동 | MCP 서버 | Hooks + CLI |
| 벡터 검색 | 처음부터 포함 | 나중에 필요 시 sqlite-vec |
| 인프라 | docker-compose | 없음 (CLI만) |
| 설치 | 서버 세팅 필요 | pip install + hook 설정 |

---

## 제품 정의 (v0.2)

### 한 줄 정의

**Project Forge는 코딩 에이전트의 경험을 축적하고, RL 스타일로 가치를 갱신하며, 세션 간에 점점 더 나은 판단을 하도록 돕는 경험 학습 CLI 도구다.**

### CLAUDE.md와의 차이

| | CLAUDE.md | Forge |
|---|---|---|
| 저장 | 플랫 텍스트 | 구조화된 경험 객체 |
| 범위 | 프로젝트 하나 | 프로젝트별 + 전역 |
| 학습 | 없음 (정적) | Q값 갱신 (점진적 개선) |
| 크로스 프로젝트 | 불가 | 전역 승격으로 지식 전이 |
| 검색 | 전체 읽기 | 패턴 매칭 + 태그 필터 → 벡터 (나중에) |

### 다른 도구와의 관계

Forge는 **경험 기억** 도구다. 실행 도구와는 완전히 별개의 축.

```
실행 도구 = "어떻게 일할지" (실행 전략)
forge     = "뭘 배웠는지"   (경험 기억)

이 둘은 직교한다. 서로 의존하지 않는다.
```

---

## 핵심 설계

### 1. 저장 구조

```
~/.forge/
  forge.db              # SQLite — 전역 + 모든 프로젝트 데이터
  config.yml            # 설정 (α, decay, 승격 기준 등)
```

SQLite 하나에 workspace_id로 구분:
- `workspace_id = "/home/user/my-api-server"` → 프로젝트 전용
- `workspace_id = "__global__"` → 전역 지식

### 2. 핵심 엔티티

**failures** — 실패 기록 (1급 객체, 핵심 차별점)
- pattern (정규화된 패턴명)
- observed_error, likely_cause, avoid_hint
- hint_quality: near_miss | preventable | environmental
- Q (유틸리티 값, 0.0~1.0)
- times_seen, times_helped, times_warned
- tags, workspace_id
- projects_seen (JSON 배열, 예: `["/path/to/project-a", "/path/to/project-b"]`)

**decisions** — 의사결정 기록
- statement, rationale, alternatives
- Q (이 결정의 rationale이 이후 판단에 도움된 정도)
- status: active | superseded | revisiting
- workspace_id

**rules** — 규칙/제약 (Q값 없음, 학습 대상 아님)
- rule_text, scope, enforcement_mode (block/warn/log)
- workspace_id
- 출력: 해당 workspace의 활성 규칙은 **항상 전부** context에 주입 (rules_max_entries로 상한만 제어)

**knowledge** — 축적된 지식
- title, content, source (organic/seeded)
- Q, tags, workspace_id
- 생성 경로:
  - **수동 시딩**: `forge record knowledge` 명령으로 직접 등록
  - **failure → knowledge 승격**: Q > 0.8이고 times_helped >= 5이면 knowledge 후보로 제안
  - 자동 생성은 하지 않음. 사용자가 확인 후 승격 (`forge promote <failure_id> --to knowledge`)

### 3. Q값 갱신 (MemRL EMA 방식)

MemRL의 수렴 보장된 업데이트 규칙을 적용:

```
Q_new ← Q_old + α(r - Q_old)

α = 0.1 (학습률)
r = 보상 신호:
  1.0 — 경고 → 실패 회피 성공
  0.0 — 경고 → 여전히 실패
  0.5 — 경고했지만 관련 없는 작업 (중립)
```

**왜 고정 증감(+0.1/-0.15)이 아닌 EMA인가:**
```
Q=0.3인 기억이 도움됨 → Q ← 0.3 + 0.1(1.0-0.3) = 0.37  (+0.07)
Q=0.9인 기억이 도움됨 → Q ← 0.9 + 0.1(1.0-0.9) = 0.91  (+0.01)

→ 낮은 Q일수록 한 번 도움됐을 때 더 많이 상승
→ 높은 Q는 이미 안정적이라 조금만 변동
→ 자연스럽게 수렴 (수학적 보장)
→ 과적합 방지: 분산 바운드 ≤ α/(2-α) × Var(r)
```

**시간 감쇠:**
```
writeback 시 각 기억의 last_used 기준으로 경과일수 계산:
  Q *= (1 - decay) ^ days_since_last_used
  decay = 0.005
  최소값: Q >= 0.05 (완전히 잊히지 않음)
```

**엔티티별 Q값 의미:**

| 엔티티 | Q값 의미 | 보상 기준 |
|--------|---------|----------|
| failure | avoid_hint가 실제로 실수를 막았는가 | 경고 후 해당 패턴 실패 없음 = 1.0 |
| decision | rationale이 이후 판단에 참고됐는가 | 같은 맥락에서 결정이 유지됨 = 1.0, superseded = 0.0 |
| knowledge | 이 지식이 작업에 도움됐는가 | 참고된 세션에서 성공 = 1.0 |

### 4. hint_quality 분류

failure 저장 시 힌트의 성격을 분류:

```
near_miss:     거의 성공, 작은 실수로 실패. 교정 힌트가 매우 구체적.
               예: "async with 안 써서 pool 고갈" → 명확한 수정 방법
               → Q 초기값: 0.6 (높게 시작)

preventable:   알려진 패턴. 회피 가능하지만 빠지기 쉬운 함정.
               예: "FK 의존성 순서 무시" → 체크리스트로 방지 가능
               → Q 초기값: 0.5 (중립)

environmental: 환경/외부 요인. 힌트로 해결 안 되는 것.
               예: "네트워크 타임아웃" → 개발자가 제어 불가
               → Q 초기값: 0.3 (낮게 시작)
```

### 5. 패턴 매칭 단계

| 수준 | 설명 | 시기 |
|------|------|------|
| P1 | 패턴명 exact match + 태그 기반 필터 | v0 |
| P2 | sqlite-vec로 유사 패턴 검색 | 데이터 쌓인 후 |
| P3 | LLM reasoning over experiences | 훨씬 나중 |

**P2 이상 검색 점수 (MemRL 공식 적용):**
```
score = (1-λ) × similarity + λ × Q

λ = 0.5 (유사도와 유용성 균등 반영)
similarity, Q 모두 z-점수 정규화
```

### 6. 전역 승격 기준

```
프로젝트 A에서 failure 기록
  → workspace_id = "/path/to/project-a"
  → projects_seen = ["/path/to/project-a"]

프로젝트 B에서 같은 pattern 발생
  → projects_seen에 추가 = ["/path/to/project-a", "/path/to/project-b"]

len(projects_seen) >= promote_threshold (기본 2)
  → 전역 복사 생성 (workspace_id = "__global__")
  → source = "organic"
  → Q값 = 프로젝트별 Q의 가중 평균 (times_seen 가중)
  → 원본 프로젝트별 기록은 유지 (삭제 안 함)
```

### 7. 컨텍스트 계층 로딩 (OpenViking + claude-mem 참고)

세션 시작 시 forge-context에 모든 기억을 쏟아넣지 않는다.

```
L0 (한 줄, ~20 토큰/개):
  "[WARN] async_connection_leak | near_miss | Q:0.85 | seen:3"
  → 전체 목록 주입 (최대 50개 = ~1000 토큰)

L1 (요약, ~300 토큰/개):
  "FastAPI에서 async session을 async with로 관리 안 하면
   connection pool이 고갈됨. avoid_hint: async with 사용 필수
   hint_quality: near_miss | Q: 0.85 | 3번 발생, 2번 도움됨"
  → Q 상위 N개만 (프로젝트 3개 + 전역 2개 = ~1500 토큰)

L2 (상세, 무제한):
  전체 에러 로그, 발생 히스토리, 관련 파일 목록
  → 필요 시 `forge detail <pattern>` 명령으로 on-demand 조회
```

**총 예산: ~3000 토큰 (설정 가능)**

```yaml
# ~/.forge/config.yml
context:
  max_tokens: 3000
  l0_max_entries: 50
  l1_project_entries: 3
  l1_global_entries: 2
  rules_max_entries: 10      # 규칙은 항상 전부 표시 (이 값은 상한)

learning:
  alpha: 0.1                 # Q값 학습률
  decay_daily: 0.005         # 일별 Q 감쇠
  q_min: 0.05                # 최소 Q값
  promote_threshold: 2       # 전역 승격 기준 (projects_seen 수)
  knowledge_promote_q: 0.8   # failure→knowledge 승격 제안 Q 기준
  knowledge_promote_helped: 5 # failure→knowledge 승격 제안 times_helped 기준

initial_q:
  near_miss: 0.6
  preventable: 0.5
  environmental: 0.3
  decision: 0.5
  knowledge: 0.5
```

---

## Claude Code 연동 (Hooks 기반)

### 사용 가능한 Hook 이벤트

| 이벤트 | 용도 | forge 활용 |
|--------|------|------------|
| SessionStart | 세션 시작 시 | forge resume → context 주입 |
| PostToolUse | 도구 실행 후 | 실패 감지 (exit code ≠ 0) |
| SessionEnd | 세션 종료 시 | forge writeback → 경험 저장 |

### Hook이 받는 데이터

```json
{
  "session_id": "abc123",
  "transcript_path": "/path/to/transcript.jsonl",
  "cwd": "/current/working/directory"
}
```

**핵심: `transcript_path`로 전체 세션 기록에 접근 가능.**

### 세션 시작 흐름

```
SessionStart hook 실행
  → forge resume --workspace $(pwd)
  → SQLite에서 이 프로젝트 + 전역 기억 조회
  → Q값 순으로 정렬
  → L0/L1 포맷으로 stdout 출력
  → Claude Code context에 자동 주입
  → 이번 세션에 주입한 경고 목록을 세션 메타로 저장 (writeback 시 비교용)
```

hook 출력 예시:
```
## Forge Experience Context

### 이 프로젝트의 실패 기록 (Q값 순)
[WARN] async_connection_leak | near_miss | Q:0.85 | seen:3 helped:2
  → async with로 session scope 관리 필수

[WARN] fk_migration_order | preventable | Q:0.7 | seen:2 helped:1
  → 마이그레이션 전 FK 의존성 그래프 확인

### 전역 지식
[INFO] docker_volume_mount_order | Q:0.9
  → volume mount 순서 틀리면 데이터 유실 가능

### 활성 규칙
[RULE] 테스트 먼저 작성 (warn)
[RULE] SQLite 금지 — 프로덕션 DB는 PostgreSQL만 (block)
```

### 세션 종료 흐름

```
SessionEnd hook 실행
  → forge writeback --workspace $(pwd) --transcript <transcript_path>

  Step 1: transcript.jsonl 파싱
    → Bash tool 중 exit code ≠ 0인 결과 추출
    → stderr에서 에러 패턴 추출 (regex)

  Step 2: 기존 패턴과 매칭
    → exact match: times_seen += 1
    → 새 패턴: 신규 failure 생성 (패턴명 자동 제안 → 나중에 사용자 교정)

  Step 3: Q값 갱신
    → 세션 시작 시 주입한 경고 목록과 비교
    → 경고한 패턴으로 실패 없음:
        times_helped += 1
        Q ← Q + α(1.0 - Q)  (보상)
    → 경고했는데 또 실패:
        Q ← Q + α(0.0 - Q)  (패널티)
        avoid_hint 재검토 플래그 설정
    → 경고 안 한 패턴은 Q 변동 없음

  Step 4: 시간 감쇠
    → 모든 기억에 대해 last_used 기준 경과일수 계산
    → Q *= (1 - decay) ^ days_since_last_used
    → Q < q_min이면 q_min으로 고정

  Step 5: 전역 승격 확인
    → projects_seen 배열 길이 >= promote_threshold → 전역 복사

  Step 6: knowledge 승격 제안 확인
    → Q >= knowledge_promote_q && times_helped >= knowledge_promote_helped
    → 조건 충족 시 로그 출력: "failure 'X'가 knowledge 승격 후보입니다"
```

### 실시간 감지 (선택적, 보조)

```
PostToolUse hook (matcher: "Bash")
  → tool_response에서 exit code 확인
  → exit code ≠ 0이면 stderr 패턴 분석
  → 기존 failure pattern과 매칭되면 즉시 경고
  → additionalContext로 Claude에 주입:
    "⚠️ Forge: 이 에러는 이전에 발생한 async_connection_leak 패턴과 유사합니다.
     avoid_hint: async with로 session scope를 관리하세요. (Q: 0.85)"
```

### 수동 기록

```bash
# 기록
forge record failure --pattern "fk_migration_order" --error "..." --hint "..." --quality near_miss
forge record decision --statement "FastAPI 유지" --rationale "..."
forge record rule --text "테스트 먼저" --mode warn
forge record knowledge --title "PostgreSQL 마이그레이션 주의점" --content "..."

# 조회
forge search --tag "fastapi" --workspace $(pwd)
forge detail async_connection_leak
forge list --workspace $(pwd) --type failure --sort q
forge list --global --type knowledge

# 관리
forge edit <id> --hint "수정된 힌트"
forge promote <id>                    # 수동 전역 승격
forge promote <id> --to knowledge     # failure → knowledge 승격
forge stats                           # 프로젝트별 기억 수, Q 분포
forge decay --dry-run                 # 감쇠 시뮬레이션
```

---

## 진화 경로

```
v0: CLI + SQLite + Hooks
    - SessionStart/End hook 연동
    - P1 패턴 매칭 (exact match + 태그)
    - L0/L1 context 주입
    - EMA 기반 Q값 갱신 (MemRL 방식)
    - hint_quality 분류 (near_miss/preventable/environmental)
    - 전역/프로젝트 분리 + 자동 승격
    - 규칙 기반 failure 추출 (exit code + stderr regex)
    - 수동 기록/교정 CLI
    - decision은 수동 기록

v1: + 정교한 추출 + 벡터
    - sqlite-vec로 P2 유사 패턴 매칭
    - 검색 점수 = (1-λ)×similarity + λ×Q (MemRL 공식)
    - LLM 기반 failure/decision 자동 추출 (선택적)
    - 중복 병합 로직 (유사도 80% 이상 → 병합 제안)
    - transcript에서 decision 패턴 자동 감지

v2: + MCP 서버 (필요 시)
    - mid-session 실시간 조회 (forge_search, forge_record)
    - Claude Code에서 능동적 호출

v3: + 풀 서버 (도메인 확장 시)
    - PostgreSQL + pgvector
    - 멀티 유저
    - P3 LLM reasoning over experiences
```

---

## 킬러 시나리오

### 시나리오 1: near-miss 학습

```
프로젝트 A에서 async DB 작업 중 거의 성공했지만 session scope 실수로 실패
→ forge writeback:
    pattern: "async_connection_leak"
    hint_quality: near_miss
    avoid_hint: "async with로 session scope 관리"
    Q: 0.6 (near_miss 초기값)

다음 세션:
→ forge resume: "[WARN] async_connection_leak | near_miss | Q:0.6"
→ Claude가 힌트대로 async with 사용 → 성공
→ Q ← 0.6 + 0.1(1.0 - 0.6) = 0.64

5번 더 도움됨:
→ Q ≈ 0.85 (안정적으로 수렴)
→ 이 near-miss 힌트가 최상위 경험으로 자리잡음
```

### 시나리오 2: 크로스 프로젝트 학습

```
프로젝트 A에서 connection leak 실패 (Q: 0.7)
프로젝트 B에서도 같은 패턴 발생 → projects_seen: 2개
→ 전역으로 승격 (Q: 가중 평균)

나중에 새 프로젝트 C에서 FastAPI + async 작업 시작
→ forge resume이 전역 지식에서 "connection leak 주의" 경고
→ 처음 보는 프로젝트인데도 경험이 전이됨
```

### 시나리오 3: 쓸모없는 기억의 자연 도태

```
environmental failure: "외부 API 타임아웃"
→ Q 초기값: 0.3
→ 경고해도 도움 안 됨 (외부 문제라 개발자가 제어 불가)
→ Q ← 0.3 + 0.1(0.0 - 0.3) = 0.27
→ 시간 감쇠 + 도움 안 됨 → Q 점점 하락
→ L1에서 제외 → L0에서도 하위로 밀림
→ 자연스럽게 가라앉음 (삭제 안 해도 됨)
```

### 시나리오 4: 실시간 경고 (PostToolUse)

```
작업 중 Bash에서 "ConnectionError: pool exhausted" 발생
→ PostToolUse hook이 stderr 감지
→ forge가 기존 패턴 "async_connection_leak"과 매칭
→ Claude context에 즉시 주입:
   "⚠️ 이전에 같은 에러 경험 있음. avoid_hint: async with 사용 (Q: 0.85)"
→ Claude가 바로 올바른 방향으로 수정
```

### 시나리오 5: failure → knowledge 승격

```
"async_connection_leak" failure:
  Q: 0.88, times_helped: 6

→ writeback에서 승격 조건 충족 (Q >= 0.8, helped >= 5)
→ 로그: "failure 'async_connection_leak'가 knowledge 승격 후보입니다"
→ 사용자: forge promote <id> --to knowledge
→ knowledge로 저장:
    title: "FastAPI async session scope 관리"
    content: avoid_hint 내용 + 발생 히스토리 요약
    source: organic
```

---

## 아직 안 잡힌 것들

- [ ] 설치/배포 방식 (pip? 단순 스크립트?)
- [ ] PostToolUse 실시간 감지의 성능 최적화 (인덱스 전략)
- [ ] decision의 Q값 갱신 트리거 — 언제 "이 결정이 유지됐다/번복됐다"를 판단하는가
- [ ] 패턴명 자동 제안 알고리즘의 구체적 구현 (stderr → 패턴명 변환 규칙)

---

## 참고 링크

### 핵심 이론
- MemRL paper: https://arxiv.org/html/2601.03192v2
  → Q값 업데이트, 2단계 검색, near-miss 발견

### 컨텍스트/메모리 시스템
- OpenViking: https://github.com/volcengine/OpenViking
  → L0/L1/L2 계층, session commit, 중복 병합
- MemOS: https://github.com/MemTensor/MemOS
  → 메모리 CRUD, inspect/edit, 피드백 루프
- claude-mem: https://github.com/thedotmack/claude-mem
  → Hook 패턴 실사용 검증, SQLite + 계층 로딩

### Claude Code 확장
- Claude Code Hooks 공식 문서
- claude-skills: https://github.com/alirezarezvani/claude-skills
- memos-api-mcp: https://github.com/MemTensor/memos-api-mcp
  → v2 MCP 서버 설계 시 참고

### 확장 비전 (v1 범위 밖)
- MiroFish: https://github.com/666ghj/MiroFish
  → 상황 예측, P3 LLM reasoning 참고

---

## 현재 상태 (2026-03-16)

- PRD v0.1 작성 완료 → `docs/prd/PRD_v0.1.md` (서버 기반, 이전 방향)
- Architecture v0.1 작성 완료 → `docs/architecture/ARCHITECTURE_v0.1.md` (서버 기반, 이전 방향)
- **아이디어 노트 v0.2 확정** → CLI + SQLite + Hooks + MemRL EMA
- 아키텍처 핵심 질문 해결 완료
- 다음 단계: v0.2 기준으로 PRD 재작성
