# Project Forge — PRD v0.2

## 1. 한 줄 정의

**코딩 에이전트의 실패·결정·규칙 경험을 구조화하여 축적하고, RL 스타일(EMA)로 경험의 가치를 갱신하며, 세션 간에 점점 더 나은 판단을 하도록 돕는 CLI 도구.**

---

## 2. 문제

코딩 에이전트는 세션이 끝나면 경험을 잃는다.

| 문제 | 결과 |
|------|------|
| 실패 휘발 | 같은 실수 반복 |
| 결정 망각 | 왜 이 선택을 했는지 복원 불가 |
| 규칙 불일치 | 프로젝트 제약이 누락됨 |
| 경험 고립 | 프로젝트 A 교훈이 B에 전이 안 됨 |

CLAUDE.md는 정적이고, claude-mem은 저장만 함. **가치 평가 + 크로스 프로젝트 학습**이 없다.

---

## 3. 타겟

AI 코딩 도구를 사용하며, 장기 작업에서 컨텍스트 손실과 반복 실패를 경험하는 개발자.

---

## 4. v0 범위

### 포함

- Failure Memory (패턴 기록 + avoid_hint + hint_quality + Q값)
- Decision Log (statement + rationale + status)
- Rules (enforcement: block/warn/log)
- Knowledge (수동 시딩 + failure→knowledge 승격)
- EMA Q값 갱신 + 시간 감쇠
- 전역 자동 승격 (projects_seen >= 2)
- L0/L1 컨텍스트 주입 (SessionStart hook)
- Writeback (SessionEnd hook + transcript 파싱)
- PostToolUse 실시간 감지 (선택적)
- CLI: record, list, search, detail, edit, promote, stats

### 제외

- 벡터 검색, LLM 자동 추출, MCP 서버, UI, 멀티 유저, 타 도구 어댑터

---

## 5. 핵심 엔티티

| 엔티티 | 핵심 필드 | Q값 의미 |
|--------|----------|---------|
| **failure** | pattern, avoid_hint, hint_quality, Q, times_seen/helped/warned, projects_seen | avoid_hint의 유용성 |
| **decision** | statement, rationale, alternatives, Q, status | rationale의 재사용 가치 |
| **rule** | rule_text, enforcement_mode (Q 없음) | — |
| **knowledge** | title, content, source, Q | 지식의 도움 정도 |

모든 엔티티는 `workspace_id`로 프로젝트 구분. `__global__`은 전역.

상세 스키마는 Architecture/TRD 문서에서 정의.

---

## 6. Q값 시스템

### 업데이트

```
Q ← Q + α(r - Q)     α=0.1

r=1.0: 경고 → 실패 회피    r=0.0: 경고 → 또 실패    r=0.5: 무관한 작업
```

### 감쇠

```
Q *= (1 - 0.005) ^ days_since_last_used     최소 0.05
```

### 초기값

| near_miss | preventable | environmental | decision | knowledge |
|-----------|-------------|---------------|----------|-----------|
| 0.6 | 0.5 | 0.3 | 0.5 | 0.5 |

---

## 7. 컨텍스트 주입

| 계층 | 크기 | 주입 기준 |
|------|------|----------|
| L0 | ~20 토큰/개 | 전체 (최대 50개) |
| L1 | ~300 토큰/개 | Q 상위 5개 (프로젝트3 + 전역2) |
| Rules | ~50 토큰/개 | 전부 (최대 10개) |
| **총합** | **~3000 토큰** | 설정 가능 |

L2(상세)는 `forge detail` CLI로 on-demand.

---

## 8. Claude Code 연동

| Hook | 명령 | 역할 |
|------|------|------|
| SessionStart | `forge resume` | Q순 L0/L1 context stdout 출력 → 자동 주입 |
| SessionEnd | `forge writeback` | transcript 파싱 → failure 추출 → Q 갱신 → 승격 확인 |
| PostToolUse | `forge detect` | Bash 실패 시 기존 패턴 매칭 → 실시간 경고 (선택적) |

---

## 9. 비목표

범용 메모리, 대화 요약, 벡터 검색(v0), LLM 자동 추출(v0), 에이전트 실행기, UI, 멀티 유저.

---

## 10. 성공 지표

| 지표 | 목표 |
|------|------|
| 같은 패턴 재발률 | 경고 후 50% 감소 |
| near-miss Q 수렴 | Q > 0.7 안정화 |
| 전역 승격 수 | 3+ 프로젝트 사용 시 5개+ organic knowledge |
| context 효율 | 100개 기억을 3000 토큰으로 |

---

## 11. 마일스톤

| 단계 | 내용 |
|------|------|
| M0: Foundation | 프로젝트 세팅, SQLite 스키마, config 로딩, CLI 프레임워크 |
| M1: Core CRUD | record, list, detail, search, edit, promote |
| M2: Hook 연동 | resume, writeback, detect + hook 설정 스크립트 |
| M3: 학습 루프 | EMA 갱신, 시간 감쇠, 전역 승격, knowledge 승격 |
| M4: 검증 | 도그푸딩, 지표 측정, 설정값 튜닝 |

---

## 12. 오픈 이슈

| 이슈 | 대응 |
|------|------|
| 설치 방식 (pip? 스크립트?) | v0 구현 시 결정 |
| stderr → 패턴명 자동 제안 규칙 | regex 기반 시작 |
| decision Q값 갱신 트리거 | v0은 수동 status 변경 시만 |
| transcript.jsonl 포맷 안정성 | 방어적 파싱 |

---

## 13. 진화 경로

```
v0: CLI + SQLite + Hooks + P1 패턴 매칭 + EMA Q값 ← 현재 범위
v1: + sqlite-vec (P2) + LLM 추출 + 중복 병합
v2: + MCP 서버 (mid-session 실시간)
v3: + PostgreSQL + 멀티 유저 + P3 LLM reasoning
```
