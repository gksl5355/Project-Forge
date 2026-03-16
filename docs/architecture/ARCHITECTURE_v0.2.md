# Project Forge — Architecture v0.2

## 1. 시스템 구조

```
┌─────────────────────────────────────────────┐
│              Claude Code Session             │
│                                             │
│  SessionStart ──→ forge resume ──→ stdout   │
│  PostToolUse  ──→ forge detect ──→ context  │
│  SessionEnd   ──→ forge writeback           │
└──────────┬──────────────────────┬───────────┘
           │ stdin (JSON)        │ transcript.jsonl
           ▼                     ▼
┌─────────────────────────────────────────────┐
│                Forge CLI (Typer)             │
│                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ Resume   │ │ Writeback│ │ Detect   │    │
│  │ Engine   │ │ Engine   │ │ Engine   │    │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘    │
│       │             │             │          │
│  ┌────┴─────────────┴─────────────┴────┐    │
│  │           Core Services              │    │
│  │                                      │    │
│  │  ┌─────────┐ ┌─────────┐           │    │
│  │  │ Q-Value │ │ Pattern │           │    │
│  │  │ Engine  │ │ Matcher │           │    │
│  │  └─────────┘ └─────────┘           │    │
│  │  ┌─────────┐ ┌─────────┐           │    │
│  │  │ Promote │ │ Context │           │    │
│  │  │ Engine  │ │ Builder │           │    │
│  │  └─────────┘ └─────────┘           │    │
│  └─────────────────┬───────────────────┘    │
│                    │                         │
│  ┌─────────────────┴───────────────────┐    │
│  │           Storage Layer              │    │
│  │         ~/.forge/forge.db            │    │
│  │           (SQLite + dataclass)       │    │
│  └──────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

---

## 2. 컴포넌트 상세

### 2.1 CLI Layer (Typer)

```
forge resume       → Resume Engine
forge writeback    → Writeback Engine
forge detect       → Detect Engine
forge record       → Core Services → Storage (Q 초기값 설정 포함)
forge list/search  → Storage Layer
forge detail       → Storage Layer
forge edit         → Core Services → Storage
forge promote      → Promote Engine → Storage
forge stats        → Q-Value Engine + Storage
forge decay        → Q-Value Engine + Storage
forge init         → Storage Layer (DB 초기화 + config 생성)
```

### 2.2 Resume Engine

**입력**: workspace_id, session_id (stdin JSON)
**출력**: stdout (L0/L1 포맷 텍스트)

```
1. Storage에서 조회:
   - failures WHERE workspace_id IN (current, '__global__') ORDER BY q DESC
   - decisions WHERE workspace_id = current AND status = 'active' ORDER BY q DESC
   - knowledge WHERE workspace_id IN (current, '__global__') ORDER BY q DESC
   - rules WHERE workspace_id = current AND active = 1

2. Context Builder:
   - L0: 전체 failure/knowledge 목록 (l0_max_entries 상한)
   - L1: Q 상위 N개 (l1_project_entries + l1_global_entries)
   - Rules: 전부 (rules_max_entries 상한)

3. sessions 테이블에 INSERT (warnings_injected = 주입한 failure pattern 목록)

4. stdout 출력 → Claude Code context 자동 주입
```

### 2.3 Writeback Engine

**입력**: workspace_id, session_id, transcript_path (stdin JSON)
**출력**: SQLite 업데이트 (단일 트랜잭션)

```
1. Transcript Parser:
   - transcript.jsonl 읽기 (방어적 파싱: 파일 없으면 skip)
   - Bash tool의 tool_result 중 exit code ≠ 0 필터
   - stderr 추출

2. Pattern Matcher (P1):
   - stderr에서 에러 키워드/클래스 추출 (regex)
   - 기존 failure의 pattern과 exact match
   - 일치 → times_seen += 1, last_used 갱신
   - 불일치 → 신규 failure INSERT (패턴명 자동 제안)

3. Q-Value Engine:
   - sessions에서 이 세션의 warnings_injected 조회
   - 경고한 패턴 vs 실제 실패 비교:
     경고했고 실패 없음 → Q ← Q + α(1.0 - Q), times_helped += 1
     경고했는데 또 실패 → Q ← Q + α(0.0 - Q), review_flag = 1
     경고 안 한 패턴 → Q 변동 없음

4. 시간 감쇠 (조건부):
   - last_used가 1일 이상 경과한 기억만 대상 (최적화)
   - Q *= (1 - decay) ^ days_since_last_used
   - Q < q_min → q_min으로 고정

5. Promote Engine:
   - 전역 승격: len(projects_seen) >= threshold → __global__ 복사
   - knowledge 승격: Q >= threshold AND helped >= threshold → stderr 로그

6. sessions 테이블 ended_at 갱신
```

### 2.4 Detect Engine

**입력**: tool_name, tool_response (stdin JSON, PostToolUse hook)
**출력**: additionalContext (stdout JSON)

```
1. tool_name != "Bash" → exit 0 (무출력)
2. exit code == 0 → exit 0
3. stderr 추출 → Pattern Matcher로 기존 패턴 매칭
4. 매칭 시 stdout JSON:
   {
     "hookSpecificOutput": {
       "hookEventName": "PostToolUse",
       "additionalContext": "⚠️ Forge: {pattern} 패턴 감지. {avoid_hint} (Q: {q})"
     }
   }
5. 매칭 없으면 → exit 0 (무출력)
```

### 2.5 Core Services

#### Q-Value Engine
- `update(q, r, alpha)` → EMA: `Q + α(r - Q)`
- `decay(q, days, decay_rate)` → `Q * (1 - decay) ^ days`
- `initial_q(hint_quality)` → config에서 매핑
- `stats(workspace_id)` → Q 분포, 엔티티별 통계
- `simulate_decay(days)` → dry-run 시뮬레이션

#### Pattern Matcher (P1)
- `match(stderr, workspace_id)` → 기존 패턴 exact match
- `suggest_pattern(stderr)` → stderr에서 패턴명 자동 제안
  - 에러 클래스명: `ConnectionError` → `connection_error`
  - 모듈명: `ModuleNotFoundError: 'X'` → `missing_module_X`
  - 일반: stderr 첫 줄 정규화 → snake_case 변환
- `match_tags(tags, workspace_id)` → json_each()로 태그 필터 (v0 풀스캔)

#### Promote Engine
- `check_global(failure)` → projects_seen 길이 확인 → 복사
- `check_knowledge(failure)` → Q + times_helped 조건 → 후보 반환
- `merge_q(failures)` → 가중 평균 (times_seen 기반)

#### Context Builder
- `build_l0(entries)` → `[WARN] {pattern} | {quality} | Q:{q} | seen:{n} helped:{n}`
- `build_l1(entries)` → L0 + avoid_hint/content 상세
- `build_rules(rules)` → `[RULE] {rule_text} ({mode})`
- `build_context(workspace_id, config)` → 예산 내에서 L0+L1+Rules 조합

### 2.6 Storage Layer

**DB**: `~/.forge/forge.db` (SQLite, Python 내장 sqlite3 모듈)

**모델**: Python dataclass로 정의. SQLAlchemy 사용하지 않음 (의존성 최소화).

**테이블**: failures, decisions, rules, knowledge, sessions

**인덱스**:
- `UNIQUE(workspace_id, pattern)` on failures — 같은 workspace에서 패턴 중복 방지
- `(workspace_id, q DESC)` on failures, knowledge — Q순 조회
- `(workspace_id, status)` on decisions
- `(workspace_id, active)` on rules
- `(session_id)` on sessions

**태그 검색**: v0은 JSON 배열 컬럼 + `json_each()` 풀스캔. 데이터 규모상 충분. 태그 검색이 병목이 되면 `entity_tags(entity_type, entity_id, tag)` 테이블로 정규화.

**트랜잭션**: writeback 전체가 단일 트랜잭션 (실패 시 전체 롤백).

**마이그레이션**: `forge.db`에 `schema_version` 테이블. CLI 실행 시 버전 확인 → 필요시 ALTER TABLE.

---

## 3. 데이터 흐름

### 3.1 세션 시작

```
Claude Code SessionStart
  → hook: forge resume --workspace $CLAUDE_PROJECT_DIR
    → Storage: SELECT (failures + decisions + knowledge + rules)
    → Context Builder: L0/L1/Rules 생성
    → Storage: INSERT session (warnings_injected)
    → stdout 출력
  → Claude Code: context 주입
```

### 3.2 작업 중 (선택적)

```
Claude Code Bash tool 실행 → exit code ≠ 0
  → hook: forge detect
    → Pattern Matcher: stderr vs 기존 패턴
    → 매칭 시: stdout JSON (additionalContext)
  → Claude Code: 경고 주입
```

### 3.3 세션 종료

```
Claude Code SessionEnd
  → hook: forge writeback --workspace $CLAUDE_PROJECT_DIR
    → Transcript Parser → Pattern Matcher → Q-Value Engine → Promote Engine
    → Storage: 단일 트랜잭션으로 전체 업데이트
```

### 3.4 수동

```
forge record failure --pattern X --hint Y --quality near_miss
  → Q-Value Engine: initial_q(near_miss) = 0.6
  → Storage: INSERT failure (q=0.6)
```

---

## 4. 프로젝트 구조

```
project-forge/
├── forge/
│   ├── __init__.py
│   ├── cli.py              # Typer CLI 진입점
│   ├── config.py            # config.yml 로딩 + 기본값
│   │
│   ├── engines/
│   │   ├── resume.py        # Resume Engine
│   │   ├── writeback.py     # Writeback Engine
│   │   ├── detect.py        # Detect Engine
│   │   └── transcript.py    # Transcript Parser
│   │
│   ├── core/
│   │   ├── qvalue.py        # Q-Value Engine
│   │   ├── matcher.py       # Pattern Matcher (P1)
│   │   ├── promote.py       # Promote Engine
│   │   └── context.py       # Context Builder
│   │
│   ├── storage/
│   │   ├── db.py            # SQLite 연결, 스키마 마이그레이션
│   │   ├── models.py        # dataclass 모델
│   │   └── queries.py       # CRUD 쿼리
│   │
│   └── hooks/
│       ├── install.py       # hook 설정 자동화
│       └── templates/       # hook shell script 템플릿
│
├── tests/
│   ├── test_qvalue.py
│   ├── test_matcher.py
│   ├── test_writeback.py
│   └── fixtures/
│       └── sample_transcript.jsonl
│
├── pyproject.toml
└── docs/
```

---

## 5. SQLite 스키마

```sql
-- 스키마 버전 관리
CREATE TABLE schema_version (
    version INTEGER NOT NULL
);
INSERT INTO schema_version VALUES (1);

CREATE TABLE failures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL,
    pattern         TEXT NOT NULL,
    observed_error  TEXT,
    likely_cause    TEXT,
    avoid_hint      TEXT NOT NULL,
    hint_quality    TEXT NOT NULL CHECK(hint_quality IN ('near_miss','preventable','environmental')),
    q               REAL NOT NULL DEFAULT 0.5,
    times_seen      INTEGER NOT NULL DEFAULT 1,
    times_helped    INTEGER NOT NULL DEFAULT 0,
    times_warned    INTEGER NOT NULL DEFAULT 0,
    tags            TEXT DEFAULT '[]',
    projects_seen   TEXT DEFAULT '[]',
    source          TEXT DEFAULT 'manual',
    review_flag     INTEGER DEFAULT 0,
    last_used       DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(workspace_id, pattern)
);

CREATE TABLE decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL,
    statement       TEXT NOT NULL,
    rationale       TEXT,
    alternatives    TEXT DEFAULT '[]',
    q               REAL NOT NULL DEFAULT 0.5,
    status          TEXT DEFAULT 'active' CHECK(status IN ('active','superseded','revisiting')),
    superseded_by   INTEGER REFERENCES decisions(id),
    tags            TEXT DEFAULT '[]',
    last_used       DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE rules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL,
    rule_text       TEXT NOT NULL,
    scope           TEXT,
    enforcement_mode TEXT DEFAULT 'warn' CHECK(enforcement_mode IN ('block','warn','log')),
    active          INTEGER DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE knowledge (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id    TEXT NOT NULL,
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    source          TEXT DEFAULT 'seeded' CHECK(source IN ('seeded','organic')),
    q               REAL NOT NULL DEFAULT 0.5,
    tags            TEXT DEFAULT '[]',
    promoted_from   INTEGER REFERENCES failures(id),
    last_used       DATETIME,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL UNIQUE,
    workspace_id    TEXT NOT NULL,
    warnings_injected TEXT DEFAULT '[]',
    started_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at        DATETIME
);

CREATE INDEX idx_failures_ws_q ON failures(workspace_id, q DESC);
CREATE INDEX idx_decisions_ws_status ON decisions(workspace_id, status);
CREATE INDEX idx_knowledge_ws_q ON knowledge(workspace_id, q DESC);
CREATE INDEX idx_rules_ws_active ON rules(workspace_id, active);
```

---

## 6. 설계 결정

### D1: SQLite 단일 파일

서버 불필요, Python 내장, 백업 용이. workspace_id로 프로젝트 분리.
동시 쓰기 제한은 코딩 에이전트 사용 패턴에서 문제없음 (순차 세션).
마이그레이션 조건: 10만 건+ or 동시 세션 → PostgreSQL.

### D2: EMA Q값

`Q ← Q + α(r - Q)`. 수렴 보장, 구현 단순. MemRL 논문 이론 근거.

### D3: Hooks 우선

별도 프로세스 불필요, context window 오버헤드 없음.
mid-session 조회 불가는 PostToolUse detect로 부분 보완.
업그레이드: v2에서 MCP 추가.

### D4: 전역 복사, 원본 유지

프로젝트별 Q와 전역 Q가 다를 수 있음. 프로젝트 컨텍스트 보존.

### D5: Knowledge 승격 반자동

자동 승격은 noise 위험. 후보 제안 → 사용자 확인.

### D6: Typer + dataclass + sqlite3

Typer: 타입 힌트 기반 CLI, Click 상위 호환.
dataclass: 의존성 없음, 타입 명확.
sqlite3: Python 내장, 외부 ORM 불필요.

### D7: 방어적 동작

- config.yml 없으면 → 기본값으로 동작
- transcript 없거나 파싱 실패 → skip (에러 아닌 경고)
- forge.db 없으면 → `forge init` 안내 또는 자동 생성
- 스키마 버전 불일치 → 자동 마이그레이션

---

## 7. 기술 요구사항

- Python 3.11+
- sqlite3 (내장)
- typer (CLI)
- pyyaml (config)
- 그 외 외부 의존성 없음
