# Project Forge — PRD v0.1 + Claude Code Reference Pack

## 문서 목적

이 문서는 **코딩 에이전트용 stateful memory runtime** 프로젝트의 초기 제품 정의서(PRD)와, Claude Code에 함께 넣어 설계/구현 참고자료로 활용할 컨텍스트 및 링크를 하나로 묶은 문서다.

이 문서의 목적은 다음 네 가지다.

1. 제품의 문제정의와 범위를 고정한다.
2. MVP에서 반드시 구현할 기능과 제외할 기능을 분리한다.
3. 데이터 모델, API, 라이프사이클, 평가 기준을 초기 수준에서 합의한다.
4. Claude Code가 설계/구현 시 참고해야 할 공식 문서와 외부 레퍼런스를 제공한다.

---

# 1. 제품 개요

## 1.1 작업명

* **1순위: Project Forge**
* 대안 1: TaskForge
* 대안 2: AgentLedger
* 대안 3: WorklogOS

현재 문서에서는 **Project Forge**를 작업명으로 사용한다.

## 1.2 한 줄 정의

**Project Forge는 세션이 바뀌어도 코딩 에이전트가 작업 목표, 최근 시도, 실패 이력, 의사결정, repo 규칙을 이어받아 다음 행동을 안정적으로 선택하도록 돕는 stateful memory runtime이다.**

## 1.3 핵심 가치

일회성 대화 요약이 아니라, 다음을 구조적으로 다룬다.

* 작업 단위의 상태 유지
* 실패 패턴 재사용 방지
* 의사결정 근거 누적
* repo별 규칙 적용
* 실행 후 write-back
* 다음 세션 재개용 context 자동 조립

---

# 2. 문제 정의

## 2.1 현재 문제

코딩 에이전트는 강력하지만, 장기 작업에서는 다음 문제가 반복된다.

1. **세션 경계 문제**

   * 세션이 끝나면 이전 맥락이 약해진다.
   * 이전 시도, 실패 사유, 보류된 의사결정이 다시 흩어진다.

2. **반복 실패 문제**

   * 이미 실패한 접근을 다시 시도한다.
   * 실패 이유가 구조화되어 저장되지 않는다.

3. **의사결정 휘발 문제**

   * "왜 이 선택을 했는지"가 남지 않는다.
   * 다음 세션이나 다른 에이전트가 의도를 복원하기 어렵다.

4. **repo 규칙 일관성 문제**

   * 팀/프로젝트별 기술 제약이 잘 적용되지 않는다.
   * 예: 테스트 필수, 특정 프레임워크 우선, DB/배포 제약, 문서 업데이트 필수 등.

5. **재개 컨텍스트 조립 비용 문제**

   * 사람이나 에이전트가 다시 작업을 이어가기 위해 이전 로그, 파일, 메모를 수동으로 뒤져야 한다.

## 2.2 왜 기존 기능만으로는 부족한가

Claude Code의 기본 메모리, subagents, hooks는 매우 유용하지만, 주로 **로컬/프로젝트 맥락과 실행 라이프사이클 제어**에 강하다.

Project Forge는 그 위에 다음을 추가로 제공해야 한다.

* 구조화된 task state
* explicit failure memory
* decision history
* vector retrieval을 통한 관련 기억 재호출
* repo-scoped policy/rules layer
* 실행/평가 후 durable write-back

즉, **기본 기능을 대체하는 제품이 아니라, 외부 지속 기억 계층을 추가하는 제품**으로 정의한다.

---

# 3. 비전과 범위

## 3.1 장기 비전

여러 코딩 에이전트와 작업 세션이 공유할 수 있는 **stateful operating layer**를 만든다.

## 3.2 v1 제품 목표

v1은 범용 메모리 OS가 아니라, 다음 목표에 집중한다.

* 코딩 에이전트의 장기 작업 지속성 강화
* 실패 반복 감소
* 의사결정 복원 가능성 향상
* repo 규칙 일관 적용
* 세션 재개 품질 개선

## 3.3 v1 제품 한계

v1은 아래를 목표로 하지 않는다.

* 범용 개인 비서 메모리
* "무엇이든 예측" 시뮬레이션 엔진
* 완전한 GraphRAG 플랫폼
* 범용 사회 시뮬레이션
* 범용 리서치/회의 어시스턴트

---

# 4. 타겟 사용자

## 4.1 1차 타겟

* Claude Code, Codex, OpenClaw, Cursor 계열 도구를 활용하는 개발자
* 장기 작업, 다단계 리팩터링, 버그 수정, 기능 구현을 자주 수행하는 AI-assisted 개발자
* repo별 규칙과 작업 로그를 체계적으로 축적하고 싶은 팀

## 4.2 대표 사용자 페르소나

### Persona A — Solo AI-native Developer

* AI 코딩 도구를 적극 사용함
* 장기 작업 중 컨텍스트 손실에 자주 시달림
* 같은 실수를 반복하지 않길 원함

### Persona B — Platform/Infra Engineer

* 프로젝트별 제약과 규칙을 엄격히 유지해야 함
* 에이전트가 팀 규칙을 일관되게 따르길 원함

### Persona C — Multi-agent Experimenter

* 여러 agent/subagent 흐름을 실험함
* task memory와 decision trail을 공통 계층으로 묶고 싶어 함

---

# 5. 사용자 문제를 해결하는 핵심 질문

Project Forge는 아래 질문에 답할 수 있어야 한다.

1. 이 작업의 현재 목표와 상태는 무엇인가?
2. 최근에 무엇을 시도했고, 무엇이 실패했는가?
3. 왜 이 설계/구현 선택을 했는가?
4. 이 repo에서 반드시 지켜야 할 규칙은 무엇인가?
5. 지금 다음으로 해야 할 가장 타당한 행동은 무엇인가?
6. 새 세션에서 이 작업을 어떤 context로 재개해야 하는가?

---

# 6. 제품 원칙

1. **대화 요약보다 구조화 우선**

   * memory는 자연어 로그가 아니라 typed memory object 중심으로 저장한다.

2. **실패 기억은 1급 객체**

   * 실패 이력은 부수 정보가 아니라 핵심 기능이다.

3. **회상(retrieval)은 작업 맥락 중심**

   * 단순 유사도 검색이 아니라 작업/파일/에러/결정과 연결되어야 한다.

4. **로컬 규칙과 외부 runtime의 역할 분리**

   * CLAUDE.md는 프로젝트 로컬 가이드
   * Forge는 durable structured memory layer

5. **MVP는 작게, 기록은 깊게**

   * 기능을 넓히기보다 task lifecycle을 정확히 닫는다.

---

# 7. 핵심 유스케이스

## 7.1 세션 재개

사용자는 하루 전 중단된 구현 작업을 재개한다.
Forge는 관련 task state, 최근 시도, 실패 원인, 수정된 파일, 남은 액션을 조립해 재개 context를 생성한다.

## 7.2 실패 반복 방지

에이전트가 이미 실패한 패턴(예: 특정 마이그레이션 순서, 잘못된 테스트 전략, API 변경 없는 임시 우회)을 다시 시도하려 하면 Forge가 경고한다.

## 7.3 의사결정 복원

왜 FastAPI를 유지하고 Flask로 바꾸지 않았는지, 왜 Qdrant를 택했고 graph DB는 보류했는지, 그 이유와 대안이 기록된다.

## 7.4 repo 규칙 적용

특정 repo에서 다음 규칙을 지켜야 한다.

* 테스트 먼저
* SQLite 금지
* README/ADR 업데이트 필수
* 운영 코드와 실험 코드를 분리

Forge는 task planning과 write-back 시 이 규칙을 회수해 반영한다.

## 7.5 평가 연계

실행 결과가 성공/실패/부분성공으로 평가되면, 그 결과를 task memory와 failure memory에 반영한다.

---

# 8. MVP 범위

## 8.1 포함 기능

### A. Task Memory

저장 항목 예시

* task_id
* title
* goal
* status
* current_summary
* next_actions
* related_files
* related_commands
* related_artifacts
* parent_task / child_task

### B. Decision Log

저장 항목 예시

* decision_id
* task_id
* decision_statement
* rationale
* alternatives_considered
* tradeoffs
* impacted_components
* confidence
* timestamp

### C. Failure Memory

저장 항목 예시

* failure_id
* task_id
* failure_pattern
* observed_error
* failed_attempt_summary
* likely_cause
* avoid_repeating_hint
* linked_files
* linked_commands
* severity

### D. Repo Rules

저장 항목 예시

* repo_id
* rule_type
* rule_text
* scope
* priority
* enforcement_mode
* examples

### E. Vector Retrieval

* task/decision/failure/rule 요약 임베딩 저장
* 관련 context recall
* session resume용 retrieval

### F. Session Resume Context Builder

* 특정 task를 재개할 때 필요한 최소 context 묶음 생성
* 최근 상태 + 관련 failure + 관련 decision + repo rules + next actions 포함

### G. Write-back Lifecycle

* 작업 종료/실행/평가 후 memory update
* success/failure/partial result 반영

### H. Basic Evaluation Linkage

* 테스트 결과, 명령 결과, 평가 결과를 task/failure memory에 연결

## 8.2 제외 기능

* 대규모 graph traversal UI
* 범용 search assistant
* 개인 생활 memory
* 자동 code execution orchestration 엔진 전체 구현
* 멀티에이전트 시뮬레이션 월드
* world-state prediction

---

# 9. 비목표(Non-goals)

1. 사용자의 모든 대화를 기억하는 범용 메모리 제품을 만들지 않는다.
2. 단순한 "채팅 요약 저장소"를 만들지 않는다.
3. GraphRAG를 우선 목표로 하지 않는다.
4. 특정 LLM 벤더 종속 제품으로 설계하지 않는다.
5. 에이전트 실행기 자체를 처음부터 새로 만들지 않는다.
6. 예측 엔진이나 디지털 트윈 세계를 v1에 넣지 않는다.

---

# 10. 시스템 아키텍처 초안

## 10.1 주요 컴포넌트

1. **Memory API Service**

   * task/decision/failure/rule CRUD
   * retrieval API
   * session resume API

2. **Relational Store (PostgreSQL)**

   * structured entities 저장
   * task, decision, failure, rule, link 관계 저장

3. **Vector Store (Qdrant)**

   * semantic retrieval용 embeddings 저장
   * task/decision/failure/rule summary retrieval

4. **Ingestion/Write-back Layer**

   * hooks, CLI, SDK, MCP-like adapter를 통해 event 수집

5. **Policy/Rules Engine**

   * repo별 규칙 적용
   * retrieve 시 우선순위 반영

6. **Resume Context Builder**

   * 다음 세션 재개용 문맥 조립

7. **Optional UI (later in MVP)**

   * task overview
   * failure patterns
   * decision timeline

## 10.2 기술 스택 제안

* Backend: FastAPI
* DB: PostgreSQL
* Vector DB: Qdrant
* Embedding: BGE-M3 또는 동급 모델
* Frontend: Vue 또는 Next.js 중 익숙한 쪽
* Auth: 초기에는 단일 사용자/로컬 우선
* Deployment: 로컬 + self-hosted 우선

## 10.3 GraphRAG에 대한 입장

GraphRAG는 흥미롭지만 v1 필수 조건이 아니다.

v1은 다음 구조로 충분하다.

* Postgres: 구조화 관계 저장
* Qdrant: semantic recall

v2에서 필요성이 검증되면 아래를 재검토한다.

* decision-to-failure causal graph
* task dependency graph
* repo knowledge graph

---

# 11. 데이터 모델 초안

## 11.1 주요 엔티티

### repositories

* id
* name
* path_or_identifier
* description
* created_at
* updated_at

### tasks

* id
* repo_id
* title
* goal
* status
* priority
* current_summary
* next_actions_json
* owner_agent
* started_at
* updated_at
* closed_at

### task_runs

* id
* task_id
* session_id
* run_type
* input_summary
* output_summary
* result_status
* started_at
* ended_at

### decisions

* id
* task_id
* statement
* rationale
* alternatives_json
* tradeoffs_json
* confidence
* created_at

### failures

* id
* task_id
* failure_pattern
* observed_error
* likely_cause
* avoid_hint
* severity
* created_at

### repo_rules

* id
* repo_id
* rule_type
* rule_text
* scope
* priority
* enforcement_mode
* created_at

### artifacts

* id
* task_id
* artifact_type
* path_or_ref
* summary
* created_at

### commands

* id
* task_run_id
* command_text
* exit_code
* output_summary
* created_at

### evaluations

* id
* task_run_id
* eval_type
* score
* verdict
* notes
* created_at

### memory_embeddings

* id
* entity_type
* entity_id
* chunk_text
* embedding_ref
* metadata_json
* created_at

## 11.2 링크 구조

* task ↔ decision
* task ↔ failure
* task ↔ artifact
* task_run ↔ command
* task_run ↔ evaluation
* repo ↔ repo_rules

## 11.3 확장 가능 구조

v2 이후 다음을 고려할 수 있다.

* memory_links 테이블
* causal relation
* contradiction relation
* superseded_by relation

---

# 12. API 초안

## 12.1 Task API

* `POST /repos/{repo_id}/tasks`
* `GET /tasks/{task_id}`
* `PATCH /tasks/{task_id}`
* `GET /repos/{repo_id}/tasks?status=open`

## 12.2 Decision API

* `POST /tasks/{task_id}/decisions`
* `GET /tasks/{task_id}/decisions`

## 12.3 Failure API

* `POST /tasks/{task_id}/failures`
* `GET /tasks/{task_id}/failures`
* `GET /failures/search?q=`

## 12.4 Repo Rule API

* `POST /repos/{repo_id}/rules`
* `GET /repos/{repo_id}/rules`
* `PATCH /rules/{rule_id}`

## 12.5 Retrieval API

* `POST /retrieve/context`

  * input: repo_id, task_id optional, query, top_k
  * output: related tasks, decisions, failures, rules

## 12.6 Resume API

* `POST /tasks/{task_id}/resume-context`

  * output:

    * task summary
    * latest state
    * relevant decisions
    * relevant failures
    * active repo rules
    * recommended next actions

## 12.7 Write-back API

* `POST /task-runs`
* `POST /task-runs/{run_id}/commands`
* `POST /task-runs/{run_id}/evaluation`
* `POST /task-runs/{run_id}/finalize`

---

# 13. 라이프사이클 설계

## 13.1 Ingestion

1. 작업 시작
2. repo 식별
3. task 생성 또는 기존 task 선택
4. repo rules 회수
5. 관련 과거 memory retrieval
6. initial working context 생성

## 13.2 Working Phase

* 에이전트가 파일 읽기/편집/명령 실행
* 중요한 decision이 생기면 decision log 추가
* 실패가 발생하면 failure memory 후보 생성

## 13.3 Evaluation Phase

* 테스트 결과, lint 결과, 명령 exit code, human feedback 수집
* 성공/실패/부분성공 판정

## 13.4 Write-back

* task summary 업데이트
* next actions 업데이트
* failure memory 확정 저장
* decision memory 확정 저장
* embeddings 업데이트

## 13.5 Resume

* 추후 세션에서 resume-context API 호출
* 재개용 최소 문맥 조립
* CLAUDE.md + repo rules + task memory를 함께 반영

---

# 14. Claude Code 연동 전략

## 14.1 기본 포지셔닝

Project Forge는 Claude Code의 내장 기능을 대체하지 않는다.

역할 분담은 다음과 같다.

### Claude Code가 잘하는 것

* 코드베이스 읽기/수정
* 명령 실행
* 로컬 프로젝트 memory 파일 활용
* subagent 기반 분업
* hooks 기반 이벤트 처리

### Forge가 추가하는 것

* durable structured memory
* cross-session task state
* failure memory
* decision log
* retrieval-ready memory store
* repo rules layer
* write-back after eval

## 14.2 CLAUDE.md와의 관계

* `CLAUDE.md`: 로컬 지침, coding conventions, repo context
* `Forge`: 구조화된 실행 기억과 작업 상태 저장소

둘은 경쟁 관계가 아니라 보완 관계다.

## 14.3 Subagent 활용 방향

Subagent는 아래처럼 역할 분리가 가능하다.

* planner
* implementer
* test-runner
* reviewer
* summarizer
* memory-writer

Forge는 이들 사이의 공통 기억 계층 역할을 수행할 수 있다.

## 14.4 Hooks 활용 방향

가능한 이벤트 예시

* task start
* pre-command
* post-command
* test complete
* evaluation complete
* session end

초기 MVP에서는 다음 두 가지부터 시작한다.

* session start → retrieval / resume context
* session end or eval end → write-back

## 14.5 Claude Code용 초기 통합 시나리오

1. 사용자가 특정 repo에서 task 시작
2. Claude Code가 CLAUDE.md 및 기본 memory를 읽음
3. Forge adapter가 repo/task 기준으로 resume context를 불러옴
4. 작업 도중 decision/failure 후보를 기록
5. 평가 후 Forge에 write-back
6. 다음 세션에서 이전 결과를 다시 retrieval

---

# 15. UX 초안

## 15.1 첫 화면

* Open tasks
* Recent failures
* Recent decisions
* Repos and active rules

## 15.2 Task detail 화면

* Goal
* Current summary
* Next actions
* Related files
* Decision timeline
* Failure timeline
* Latest evaluation

## 15.3 Resume panel

* Resume summary
* Must-remember rules
* Avoid these mistakes
* Best next actions

---

# 16. 성공 지표

## 16.1 제품 지표

1. 세션 재개 시간 단축

   * 사용자가 다시 작업을 이해하는 데 걸리는 시간 감소

2. 반복 실패율 감소

   * 이미 저장된 failure pattern이 다시 발생하는 비율 감소

3. decision recoverability 향상

   * 특정 설계 결정의 근거를 재구성할 수 있는 비율 증가

4. repo rule violation 감소

   * 명시된 규칙 위반 빈도 감소

5. resume context 품질 향상

   * 사용자가 "이제 어디서 이어야 하는지 알겠다"고 판단하는 비율 증가

## 16.2 초기 정성 평가 질문

* 이 task를 다시 이해하는 데 도움이 되었는가?
* 불필요한 재시도를 줄였는가?
* 다음 액션이 타당했는가?
* failure memory가 실제로 유용했는가?
* repo 규칙이 잘 반영되었는가?

---

# 17. 리스크와 오픈 이슈

## 17.1 리스크

1. 너무 많은 memory를 저장해 retrieval noise가 커질 수 있음
2. decision/failure를 자동 추출할 때 품질이 낮을 수 있음
3. rules 적용이 과하면 에이전트 유연성이 떨어질 수 있음
4. task granularity가 너무 크거나 작으면 운영성이 나빠질 수 있음
5. 도구별 통합 방식이 달라 공통 adapter 설계가 어려울 수 있음

## 17.2 오픈 이슈

1. task 단위는 어떻게 자를 것인가?
2. failure pattern의 canonical form은 어떻게 정의할 것인가?
3. command output 저장량은 어느 정도가 적정한가?
4. embeddings 재생성 정책은 어떻게 가져갈 것인가?
5. human-in-the-loop correction을 어떤 단계에서 넣을 것인가?
6. rule priority 충돌 시 어떤 정책으로 해결할 것인가?

---

# 18. 마일스톤 제안

## Milestone 0 — Foundation

* repo, task, decision, failure, rule 스키마 정의
* 기본 CRUD API 구현
* Postgres/Qdrant 연결

## Milestone 1 — Resume MVP

* task resume context API 구현
* retrieval pipeline 구현
* basic summarization 구현

## Milestone 2 — Write-back MVP

* task run, command, evaluation 기록
* failure/decision write-back 구현

## Milestone 3 — Claude Code Adapter

* 시작/종료 훅 기반 연동
* CLAUDE.md와 함께 사용하는 실전 워크플로우 구현

## Milestone 4 — Basic UI

* open tasks, failures, decisions, rules 조회 화면

## Milestone 5 — Evaluation Loop

* 반복 실패율, 재개 시간, rule violation 등 측정

---

# 19. Claude Code에 넣을 컨텍스트 블록

아래 블록은 Claude Code에 그대로 전달할 수 있는 초기 컨텍스트다.

```md
## Project context

You are helping design and implement a product called "Project Forge" (working title).

### Product thesis
Project Forge is a stateful memory runtime for coding agents.
It should help an agent resume long-running work across sessions, avoid repeated failures, preserve decision rationale, and enforce repo-specific rules.

### What this product is NOT
- Not a generic personal assistant memory
- Not a broad "predict anything" simulation engine
- Not a simple conversation summarizer
- Not just a skill collection
- Not full GraphRAG in v1

### v1 focus
- Task Memory
- Decision Log
- Failure Memory
- Repo Rules
- Vector Retrieval
- Session Resume Context Builder
- Basic Evaluation Linkage

### Design instruction
Use Claude Code's built-in concepts as the local/runtime baseline:
- project memory / CLAUDE.md
- subagents
- hooks

But do NOT stop there.
Design an external durable memory layer that goes beyond local project memory:
- structured task state
- explicit failure memory
- decision history
- repo-scoped policy/rules
- retrieval-ready memory schema
- write-back after execution/evaluation

### Product principles
- Prefer structured memory over generic summaries
- Treat failure memory as a first-class object
- Keep v1 small but operationally complete
- Separate local repo guidance from external durable runtime memory
- Postgres + vector DB first, GraphRAG later

### Output required
Produce:
1. PRD v0.1
2. system architecture
3. data model
4. API draft
5. ingestion / retrieval / write-back lifecycle
6. MVP milestone plan
7. non-goals
8. risks and open questions
```

---

# 20. Claude Code용 구현 요청본 초안

아래는 Claude Code에 직접 던질 수 있는 구현 요청 초안이다.

```md
We are building Project Forge, a stateful memory runtime for coding agents.

Your task:
Design the backend-first MVP with FastAPI + PostgreSQL + Qdrant.

Required scope:
1. repository/task/decision/failure/repo_rule schema
2. CRUD APIs
3. retrieval API for context recall
4. resume-context API
5. task run / evaluation / finalize APIs
6. embedding pipeline interface
7. clear separation between structured DB storage and vector retrieval storage

Constraints:
- Do not implement GraphRAG in v1
- Do not design a generic assistant memory product
- Focus on coding-agent workflows only
- Keep the system self-hostable
- Make failure memory a first-class entity
- Support repo-scoped rules with priority and scope

Deliverables:
- folder structure
- DB schema
- FastAPI routers
- Pydantic models
- service layer outline
- Qdrant collection design
- sample resume-context response
- implementation plan by milestones
```

---

# 21. 참고 링크

## 21.1 Claude Code 공식 문서

* Claude Code Overview
  [https://code.claude.com/docs/en/overview](https://code.claude.com/docs/en/overview)

* How Claude remembers your project
  [https://code.claude.com/docs/en/memory](https://code.claude.com/docs/en/memory)

* Create custom subagents
  [https://code.claude.com/docs/en/sub-agents](https://code.claude.com/docs/en/sub-agents)

* Hooks reference
  [https://code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)

## 21.2 Claude Code 확장/스킬 참고

* claude-skills
  [https://github.com/alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills)

* claude-code-skill-factory
  [https://github.com/alirezarezvani/claude-code-skill-factory](https://github.com/alirezarezvani/claude-code-skill-factory)

* claude-mem
  [https://github.com/thedotmack/claude-mem](https://github.com/thedotmack/claude-mem)

## 21.3 메모리 시스템 참고

* MemRL paper
  [https://arxiv.org/html/2601.03192v2](https://arxiv.org/html/2601.03192v2)

* MemOS
  [https://github.com/MemTensor/MemOS](https://github.com/MemTensor/MemOS)

* memos-api-mcp
  [https://github.com/MemTensor/memos-api-mcp](https://github.com/MemTensor/memos-api-mcp)

## 21.4 스킬/에이전트 생태계 참고

* awesome-openclaw-skills
  [https://github.com/VoltAgent/awesome-openclaw-skills](https://github.com/VoltAgent/awesome-openclaw-skills)

## 21.5 확장 비전 참고

* MiroFish-Ko
  [https://github.com/ByeongkiJeong/MiroFish-Ko](https://github.com/ByeongkiJeong/MiroFish-Ko)

* MiroFish original
  [https://github.com/666ghj/MiroFish](https://github.com/666ghj/MiroFish)

---

# 22. 참고자료를 어떻게 읽을지

## 바로 반영할 것

* Claude Code Overview
* Memory
* Subagents
* Hooks

## 구현 힌트용

* claude-skills
* claude-code-skill-factory
* claude-mem

## 메모리 아키텍처 참고용

* MemRL
* MemOS
* memos-api-mcp

## 확장 비전 참고용

* MiroFish-Ko
* MiroFish

주의: MiroFish 계열은 v1 구현 범위가 아니라, 이후 simulation sandbox 확장 아이디어 수준으로만 참고한다.

---

# 23. 초기 폴더 구조 제안

```text
project-forge/
├─ apps/
│  ├─ api/
│  │  ├─ main.py
│  │  ├─ routers/
│  │  ├─ schemas/
│  │  ├─ services/
│  │  └─ dependencies/
│  └─ worker/
│     ├─ embedding/
│     └─ writeback/
├─ domain/
│  ├─ tasks/
│  ├─ decisions/
│  ├─ failures/
│  ├─ rules/
│  └─ retrieval/
├─ infra/
│  ├─ db/
│  ├─ qdrant/
│  ├─ logging/
│  └─ config/
├─ adapters/
│  ├─ claude_code/
│  ├─ codex/
│  └─ generic_cli/
├─ docs/
│  ├─ prd/
│  ├─ adr/
│  └─ api/
├─ scripts/
├─ tests/
└─ README.md
```

---

# 24. 최종 정리

Project Forge의 v1은 다음 한 문장으로 요약된다.

**코딩 에이전트가 장기 작업을 세션 간에 안정적으로 이어가도록, task memory, decision log, failure memory, repo rules, vector retrieval, write-back lifecycle을 제공하는 stateful runtime을 만든다.**

이 문서에서 가장 중요한 결정은 세 가지다.

1. **도메인은 코딩 에이전트로 한정한다.**
2. **최소 vector DB는 포함하되 GraphRAG는 후순위로 둔다.**
3. **Claude Code 기본 기능 위에 올라가는 durable memory layer로 포지셔닝한다.**
