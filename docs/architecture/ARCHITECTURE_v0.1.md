# Project Forge — Architecture v0.1

> ⚠️ **DEPRECATED**: This document describes the initial server-based design (FastAPI + PostgreSQL + Qdrant). The project has pivoted to a CLI-first approach. See [ARCHITECTURE v0.2](ARCHITECTURE_v0.2.md) and related v0.2 documents for the current design.

## 1. 아키텍처 비전

Project Forge는 **도메인 중립 experience runtime**이다.

핵심 전제:
- 코어는 도메인을 모른다
- 도메인 지식은 rules + knowledge seeding + 자연 축적으로 주입된다
- 코딩 에이전트가 first adapter, 금융/인프라 등 리스크 도메인이 확장 대상

```
"실수가 비싼 곳에서, 경험이 축적될수록 더 나은 판단을 하게 되는 시스템"
```

---

## 2. 시스템 전체 구조

```
┌──────────────────────────────────────────────────────┐
│                   Domain Adapters                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │
│  │  Claude   │  │  Codex   │  │  Finance/Infra   │   │
│  │  Code     │  │  CLI     │  │  (future)        │   │
│  └────┬─────┘  └────┬─────┘  └────────┬─────────┘   │
│       │              │                 │              │
│       └──────────────┼─────────────────┘              │
│                      │                                │
├──────────────────────┼────────────────────────────────┤
│                 API Gateway                           │
│            (FastAPI + MCP Server)                     │
├──────────────────────┼────────────────────────────────┤
│                      │                                │
│  ┌───────────────────┴───────────────────────┐       │
│  │           Experience Core                  │       │
│  │                                            │       │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐  │       │
│  │  │  Task    │ │ Decision │ │ Failure  │  │       │
│  │  │  Engine  │ │ Registry │ │ Registry │  │       │
│  │  └──────────┘ └──────────┘ └──────────┘  │       │
│  │                                            │       │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐  │       │
│  │  │ Write-   │ │ Resume   │ │ Eval     │  │       │
│  │  │ back     │ │ Builder  │ │ Linker   │  │       │
│  │  └──────────┘ └──────────┘ └──────────┘  │       │
│  └───────────────────┬───────────────────────┘       │
│                      │                                │
│  ┌───────────────────┴───────────────────────┐       │
│  │           Knowledge Layer                  │       │
│  │                                            │       │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐  │       │
│  │  │ Rules    │ │ Pattern  │ │ Knowledge│  │       │
│  │  │ Engine   │ │ Detector │ │ Store    │  │       │
│  │  └──────────┘ └──────────┘ └──────────┘  │       │
│  │                                            │       │
│  │  ┌──────────────────────────────────────┐  │       │
│  │  │  Retrieval Engine                    │  │       │
│  │  │  (structured query + vector search)  │  │       │
│  │  └──────────────────────────────────────┘  │       │
│  └───────────────────┬───────────────────────┘       │
│                      │                                │
├──────────────────────┼────────────────────────────────┤
│                 Storage Layer                         │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │  PostgreSQL   │  │  pgvector    │                  │
│  │  (structured) │  │  (semantic)  │                  │
│  └──────────────┘  └──────────────┘                  │
└──────────────────────────────────────────────────────┘
```

---

## 3. 레이어별 상세 설계

### 3.1 Storage Layer

단일 PostgreSQL 인스턴스에 pgvector 확장을 사용한다.

**왜 Qdrant가 아닌 pgvector인가:**
- 초기에 인프라 의존성 최소화
- 구조화 데이터와 벡터가 같은 트랜잭션 안에서 처리됨
- 데이터 규모가 작은 초기에는 pgvector로 충분
- 스케일이 필요해지면 Qdrant로 마이그레이션 가능 (retrieval engine만 교체)

**스키마 핵심 원칙:**
- 모든 엔티티는 `workspace_id`를 가짐 (repo보다 넓은 개념, 도메인 중립)
- 도메인 특화 필드는 `metadata_json`으로 처리 (코어 스키마는 도메인 불문)
- 임베딩은 엔티티와 같은 DB에 저장, `entity_type + entity_id`로 참조

```sql
-- 핵심 테이블 요약
workspaces          -- repo, 프로젝트, 도메인 등 작업 공간 단위
tasks               -- 작업 단위, workspace 소속
task_runs           -- 특정 task의 실행 세션
decisions           -- 의사결정 기록
failures            -- 실패 기록 (1급 객체)
rules               -- workspace별 규칙/제약
knowledge_entries   -- 축적된 지식 (자연 축적 + 시딩)
evaluations         -- 실행 결과 평가
embeddings          -- pgvector 임베딩 (모든 엔티티 공용)
```

### 3.2 Knowledge Layer

Knowledge Layer는 세 가지 역할을 수행한다.

#### A. Rules Engine — 제약과 규칙

workspace에 바인딩된 명시적 규칙. 도메인마다 다르다.

```
코딩: "테스트 먼저", "SQLite 금지"
금융: "리스크 한도 초과 시 승인 필요", "백테스트 없이 배포 금지"
인프라: "프로덕션 변경은 canary 필수"
```

규칙은 **enforcement_mode**를 가진다:
- `block`: 위반 시 진행 차단
- `warn`: 위반 시 경고만
- `log`: 위반 기록만

#### B. Pattern Detector — 경험에서 패턴 추출

축적된 failure/decision 데이터에서 반복 패턴을 감지한다.

**L1: Exact Match (v1)**
- 동일한 failure_pattern이 재등장하면 경고
- 구현: failure_pattern 필드의 정규화된 문자열 매칭

**L2: Similar Match (v1)**
- 유사한 상황에서 유사한 접근이 실패한 이력이 있으면 경고
- 구현: pgvector cosine similarity, threshold 기반

**L3: Contextual Prediction (v2)**
- 현재 상황 + 과거 경험을 LLM에 넘겨 "이 접근의 리스크"를 추론
- 구현: retrieve relevant experiences → LLM reasoning → risk score
- v1에서는 설계만, 구현은 v2

#### C. Knowledge Store — 축적되는 지식

두 가지 경로로 지식이 쌓인다:

**자연 축적 (Organic)**
- 반복 성공한 패턴 → "이 접근은 이 상황에서 잘 동작한다"
- 반복 실패한 패턴 → "이 접근은 이 상황에서 위험하다"
- 확정된 decision의 rationale → 재사용 가능한 판단 근거

**초기 시딩 (Seeding)**
- workspace 생성 시 도메인 지식을 bulk import
- 형식: structured knowledge entries (title, content, tags, source)
- 예: 팀의 기존 ADR 문서, 금융 규정 요약, 인프라 runbook 핵심 등

```
knowledge_entry:
  title: "PostgreSQL 대규모 마이그레이션 시 주의사항"
  content: "..."
  source: "organic | seeded | imported"
  confidence: 0.85      # 자연 축적은 경험 횟수에 비례해 증가
  tags: ["postgresql", "migration", "risk"]
  workspace_id: ...
```

#### D. Retrieval Engine

모든 recall은 이 엔진을 통한다.

```
Input:  query (자연어) + workspace_id + context (현재 task, 파일 등)
Output: ranked list of relevant entities
        (tasks, decisions, failures, rules, knowledge)
```

**검색 전략 (Hybrid):**
1. **Structured query**: workspace_id, entity_type, status 등으로 1차 필터
2. **Vector search**: pgvector로 semantic similarity
3. **Recency bias**: 최근 경험에 가중치
4. **Relevance scoring**: structured score + vector score + recency 가중 합산

---

### 3.3 Experience Core

Experience Core는 도메인을 모르는 순수 경험 관리 엔진이다.

#### A. Task Engine

```
Task Lifecycle:

  created → active → paused → active → completed
                 ↘                    ↗
                  → blocked → active ─┘
                 ↘
                  → failed → (retry → active)
                 ↘
                  → cancelled
```

Task는 다음을 소유한다:
- 0..N task_runs (실행 세션)
- 0..N decisions
- 0..N failures
- 0..N child tasks (계층 구조)

**핵심 필드:**
- `goal`: 이 task가 달성하려는 것 (불변)
- `current_summary`: 현재 상태 요약 (write-back 시 갱신)
- `next_actions`: 다음 해야 할 것들 (write-back 시 갱신)
- `metadata_json`: 도메인 특화 데이터

#### B. Decision Registry

의사결정을 1급 객체로 저장한다.

```
decision:
  statement: "FastAPI를 유지하고 Flask로 바꾸지 않는다"
  rationale: "async 지원, 자동 문서 생성, 기존 코드 호환"
  alternatives:
    - option: "Flask로 전환"
      rejected_reason: "async 미지원, 마이그레이션 비용"
    - option: "Django REST"
      rejected_reason: "오버스펙"
  confidence: 0.8
  status: active | superseded | revisiting
```

**superseded 관계**: 나중에 결정이 번복되면 새 decision을 만들고 이전 것을 `superseded`로 표시. 왜 바꿨는지가 남는다.

#### C. Failure Registry

실패를 1급 객체로 저장한다. **이것이 Forge의 핵심 차별점.**

```
failure:
  pattern: "migration_order_dependency"     # 정규화된 패턴명
  observed_error: "ForeignKeyViolation: ..."
  context_summary: "users 테이블 전에 orders 테이블을 마이그레이션하려 함"
  likely_cause: "테이블 간 FK 의존성 무시"
  avoid_hint: "마이그레이션 전 FK 의존성 그래프를 확인할 것"
  severity: high
  recurrence_count: 0  # 같은 패턴 재발 시 증가
```

**pattern 필드의 역할:**
- 자연어 에러 메시지가 아닌, 정규화된 패턴명
- 같은 유형의 실패를 묶는 키
- Pattern Detector의 L1 매칭에 사용
- 자동 추출 + 사람/에이전트가 교정 가능

#### D. Write-back Engine

실행 종료 또는 평가 완료 시 experience를 업데이트한다.

```
Write-back 트리거:
  1. task_run 종료 시 → task.current_summary, task.next_actions 갱신
  2. 평가 완료 시 → failure 확정 or 성공 기록
  3. 명시적 호출 시 → decision/failure 수동 기록

Write-back 파이프라인:
  event → validate → update entities → update embeddings → notify
```

**임베딩 갱신 전략:**
- 엔티티 생성/수정 시 비동기로 임베딩 재생성
- batch 재생성은 별도 워커로 (초기에는 동기도 가능)

#### E. Resume Builder

특정 task를 재개할 때 필요한 최소 context를 조립한다.

```
Resume Context 구조:

{
  "task": {
    "goal": "...",
    "current_summary": "...",
    "next_actions": ["..."],
    "status": "paused"
  },
  "recent_decisions": [...],       # 이 task의 최근 결정들
  "relevant_failures": [...],      # 이 task + 유사 task의 실패들
  "active_rules": [...],           # 이 workspace의 활성 규칙들
  "related_knowledge": [...],      # 관련 지식 (vector retrieval)
  "warnings": [                    # Pattern Detector 경고
    "이전에 같은 접근으로 실패한 이력이 있음: #failure-12"
  ]
}
```

#### F. Eval Linker

외부 평가 결과를 experience에 연결한다.

```
evaluation:
  task_run_id: ...
  eval_type: "test" | "lint" | "review" | "manual" | "custom"
  verdict: "pass" | "fail" | "partial"
  score: 0.0~1.0 (optional)
  detail_json: { ... }  # 도메인별 상세 (테스트 결과, 리뷰 코멘트 등)
```

평가 결과에 따라:
- `pass` → task 진행, 성공 패턴 기록
- `fail` → failure 후보 생성, Pattern Detector에 등록
- `partial` → task에 경고 추가, next_actions 갱신

---

### 3.4 API Gateway

두 가지 인터페이스를 제공한다.

#### A. REST API (FastAPI)

모든 CRUD + 비즈니스 로직. 사람과 에이전트 모두 사용.

```
# Workspace
POST   /workspaces
GET    /workspaces/{id}

# Task
POST   /workspaces/{ws_id}/tasks
GET    /workspaces/{ws_id}/tasks
GET    /tasks/{id}
PATCH  /tasks/{id}

# Task Run
POST   /tasks/{id}/runs
PATCH  /runs/{id}
POST   /runs/{id}/finalize

# Decision
POST   /tasks/{id}/decisions
GET    /tasks/{id}/decisions

# Failure
POST   /tasks/{id}/failures
GET    /tasks/{id}/failures
GET    /workspaces/{ws_id}/failures/search

# Rules
POST   /workspaces/{ws_id}/rules
GET    /workspaces/{ws_id}/rules
PATCH  /rules/{id}

# Knowledge
POST   /workspaces/{ws_id}/knowledge
POST   /workspaces/{ws_id}/knowledge/seed    # bulk import
GET    /workspaces/{ws_id}/knowledge/search

# Retrieval
POST   /retrieve
  → input:  { workspace_id, query, context?, top_k?, entity_types? }
  → output: { results: [...], warnings: [...] }

# Resume
POST   /tasks/{id}/resume-context
  → output: ResumeContext (위 3.3.E 참조)

# Evaluation
POST   /runs/{id}/evaluations
```

**인증**: 초기에는 API key 기반 단일 사용자. 헤더: `X-Forge-Key`.

#### B. MCP Server Interface

Claude Code 등 MCP 지원 클라이언트에서 tool로 호출할 수 있도록 MCP server를 제공한다.

```
MCP Tools:
  forge_resume_task     → resume-context API 호출
  forge_record_decision → decision 생성
  forge_record_failure  → failure 생성
  forge_check_rules     → 현재 workspace 규칙 조회
  forge_search          → retrieval API 호출
  forge_finalize_run    → write-back 트리거
```

**왜 MCP인가:**
- Claude Code의 hook만으로는 양방향 통신이 어려움
- MCP server로 구현하면 에이전트가 능동적으로 Forge를 호출 가능
- hook은 보조 수단 (세션 종료 시 자동 write-back 등)

---

### 3.5 Domain Adapters

어댑터는 도메인 특화 로직을 코어와 분리한다.

#### Adapter Interface

```python
class DomainAdapter(Protocol):
    """도메인 어댑터가 구현해야 할 인터페이스"""

    def extract_failure_pattern(self, raw_error: str, context: dict) -> str:
        """도메인 에러에서 정규화된 failure pattern 추출"""
        ...

    def extract_decision_candidates(self, session_log: str) -> list[DecisionCandidate]:
        """세션 로그에서 의사결정 후보 추출"""
        ...

    def format_resume_context(self, raw_context: ResumeContext) -> str:
        """도메인에 맞게 resume context 포맷팅"""
        ...

    def get_default_rules(self) -> list[Rule]:
        """도메인 기본 규칙 반환"""
        ...

    def get_seed_knowledge(self) -> list[KnowledgeEntry]:
        """도메인 초기 지식 반환"""
        ...
```

#### Claude Code Adapter (v1)

```
역할:
  - failure pattern 추출: exit code, 테스트 에러, lint 에러 파싱
  - decision 추출: 코드 변경 이유, 라이브러리 선택 이유
  - resume context 포맷: CLAUDE.md 스타일로 변환
  - 기본 규칙: 코딩 컨벤션, 테스트 정책 등
  - MCP server로 Claude Code에 연결

연동 흐름:
  1. Claude Code 시작 → MCP로 forge_resume_task 호출
  2. 작업 중 → forge_check_rules, forge_search 수시 호출
  3. 결정 시 → forge_record_decision 호출
  4. 실패 시 → forge_record_failure 호출
  5. 종료 시 → forge_finalize_run 호출 (hook 또는 수동)
```

---

## 4. 데이터 흐름

### 4.1 새 작업 시작

```
User/Agent → POST /workspaces/{ws}/tasks (goal 설정)
           → POST /tasks/{id}/runs (세션 시작)
           → POST /tasks/{id}/resume-context (이전 경험 조회)
           ← ResumeContext (관련 failure, decision, rules, knowledge)
           → 작업 시작
```

### 4.2 작업 중

```
작업 중 → 에러 발생
       → POST /tasks/{id}/failures (failure 기록)
       ← Pattern Detector: "유사 패턴 경고" (있으면)

작업 중 → 설계 결정
       → POST /tasks/{id}/decisions (decision 기록)

작업 중 → 관련 경험 필요
       → POST /retrieve (query + context)
       ← ranked results
```

### 4.3 작업 종료

```
작업 완료 → POST /runs/{id}/evaluations (평가 결과)
         → POST /runs/{id}/finalize
           내부적으로:
             - task.current_summary 갱신
             - task.next_actions 갱신
             - failure 확정/해소
             - embeddings 재생성
             - knowledge 후보 생성 (반복 패턴 → 지식화)
```

### 4.4 재개

```
다음 세션 → POST /tasks/{id}/resume-context
          ← 이전 상태 + 실패 이력 + 결정 이력 + 규칙 + 경고
          → 이어서 작업
```

---

## 5. 핵심 설계 결정

### D1: 도메인 중립 코어 + 어댑터 패턴

**결정**: 코어는 task/decision/failure/rule/knowledge만 알고, 도메인 해석은 어댑터에 위임한다.

**이유**: 코딩→금융→인프라 확장 시 코어를 건드리지 않기 위해. "migration FK 에러"와 "margin call 미처리"는 코어 입장에서 둘 다 failure일 뿐.

**트레이드오프**: 어댑터 인터페이스가 너무 추상적이면 각 도메인에서 제대로 동작하지 않을 수 있음. v1에서 Claude Code 어댑터를 충분히 구체적으로 만들어서 인터페이스를 검증해야 함.

### D2: pgvector 우선, Qdrant는 후순위

**결정**: PostgreSQL + pgvector로 시작한다.

**이유**: 인프라 단순화, 트랜잭션 일관성, 초기 데이터 규모에 충분.

**마이그레이션 조건**: 임베딩 10만 건 이상 or 검색 latency > 200ms 시 Qdrant 도입 검토.

### D3: MCP Server를 주 연동 방식으로

**결정**: Claude Code 연동은 MCP server가 primary, hook은 보조.

**이유**: hook은 단방향(이벤트 알림)이지만, MCP는 양방향(에이전트가 능동적으로 조회/기록 가능).

### D4: Failure Pattern 정규화는 어댑터 + 사람 교정

**결정**: 어댑터가 자동 추출하되, 사람이 교정할 수 있다.

**이유**: 자동 추출 품질이 초기에는 낮을 수 있음. 교정 루프가 있으면 점진적으로 개선됨.

### D5: Knowledge는 명시적 엔티티로 관리

**결정**: knowledge를 failure/decision과 별개의 1급 엔티티로 관리한다.

**이유**: failure는 "이건 안 됐다", decision은 "이걸 선택했다", knowledge는 "이건 알고 있다"로 역할이 다름. knowledge는 외부에서 시딩할 수도 있고, 경험에서 자연 생성될 수도 있어서 별도 관리가 필요.

### D6: 예측은 L1→L2→L3 점진 도입

**결정**: v1은 L1(exact match) + L2(vector similarity), L3(LLM reasoning)는 v2.

**이유**: L3는 LLM 호출 비용 + 품질 불확실성이 있음. L1+L2만으로도 "이전에 실패했던 것" 경고는 충분히 가능.

---

## 6. 폴더 구조

```
project-forge/
├── apps/
│   ├── api/                    # FastAPI 애플리케이션
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── workspaces.py
│   │   │   ├── tasks.py
│   │   │   ├── runs.py
│   │   │   ├── decisions.py
│   │   │   ├── failures.py
│   │   │   ├── rules.py
│   │   │   ├── knowledge.py
│   │   │   ├── retrieval.py
│   │   │   └── resume.py
│   │   ├── schemas/            # Pydantic models (request/response)
│   │   ├── dependencies/       # DI, auth, db session
│   │   └── middleware/         # logging, error handling
│   │
│   ├── mcp/                    # MCP Server
│   │   ├── server.py
│   │   └── tools/
│   │       ├── resume.py
│   │       ├── record.py
│   │       ├── search.py
│   │       └── rules.py
│   │
│   └── worker/                 # 비동기 워커
│       ├── embedding.py        # 임베딩 생성/갱신
│       └── knowledge.py        # 경험→지식 변환
│
├── core/                       # Experience Core (도메인 로직)
│   ├── tasks/
│   │   ├── models.py           # SQLAlchemy models
│   │   ├── service.py          # 비즈니스 로직
│   │   └── schemas.py          # 내부 데이터 구조
│   ├── decisions/
│   ├── failures/
│   ├── rules/
│   ├── knowledge/
│   ├── retrieval/
│   │   ├── engine.py           # hybrid retrieval
│   │   └── scoring.py          # relevance scoring
│   ├── resume/
│   │   └── builder.py
│   ├── patterns/
│   │   ├── detector.py         # L1/L2 pattern detection
│   │   └── normalizer.py       # failure pattern 정규화
│   ├── writeback/
│   │   └── engine.py
│   └── evaluation/
│       └── linker.py
│
├── adapters/                   # Domain Adapters
│   ├── base.py                 # DomainAdapter protocol
│   ├── claude_code/
│   │   ├── adapter.py
│   │   ├── failure_parser.py
│   │   └── resume_formatter.py
│   └── generic/
│       └── adapter.py
│
├── infra/                      # 인프라/설정
│   ├── db/
│   │   ├── connection.py
│   │   ├── migrations/         # Alembic
│   │   └── seed.py
│   ├── embedding/
│   │   ├── provider.py         # 임베딩 모델 인터페이스
│   │   └── bge_m3.py           # BGE-M3 구현
│   ├── config.py
│   └── logging.py
│
├── docs/
│   ├── prd/
│   ├── architecture/
│   ├── trd/
│   └── adr/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── scripts/
│   ├── setup_db.py
│   └── seed_knowledge.py
│
├── docker-compose.yml
├── pyproject.toml
├── alembic.ini
└── README.md
```

---

## 7. 인프라 요구사항

### 최소 구성 (로컬 개발)
- Python 3.11+
- PostgreSQL 15+ with pgvector
- Docker (optional, for PostgreSQL)

### 임베딩 모델
- BGE-M3: 로컬 추론 (GPU 권장, CPU도 가능하나 느림)
- 대안: OpenAI embeddings API (빠르지만 외부 의존)
- 인터페이스를 추상화해서 교체 가능하게 설계

### 배포 (v1)
- docker-compose: api + postgres + worker
- self-hosted 우선
- 클라우드 배포는 v2

---

## 8. 미해결 설계 질문

1. **Knowledge 자동 생성 기준**: 몇 번 반복되면 failure→knowledge로 승격하는가?
2. **임베딩 모델 선택**: 로컬(BGE-M3) vs API(OpenAI)? GPU 없으면?
3. **MCP server 인증**: Claude Code에서 MCP 호출 시 인증은 어떻게?
4. **멀티 워크스페이스**: 한 사용자가 여러 workspace를 가질 때 cross-workspace retrieval이 필요한가?
5. **Conflict resolution**: 같은 task에 여러 에이전트가 동시에 write-back하면?
