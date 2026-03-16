# Project Forge — TRD v0.2

## 1. 기술 스택

| 항목 | 선택 | 이유 |
|------|------|------|
| 언어 | Python 3.11+ | 타입 힌트, sqlite3 내장 |
| CLI | Typer | 타입 기반 CLI, Click 상위 호환 |
| DB | sqlite3 (내장) | 외부 의존성 없음 |
| Config | PyYAML | config.yml 파싱 |
| 테스트 | pytest | 표준 |
| 패키징 | pyproject.toml + pip | 표준 설치 경로 |

**외부 의존성 총 3개**: typer, pyyaml, pytest (dev)

---

## 2. 프로젝트 구조

```
project-forge/
├── forge/
│   ├── __init__.py          # 버전 정보
│   ├── cli.py               # Typer 앱, 모든 명령 등록
│   ├── config.py            # Config dataclass + YAML 로딩 + 기본값
│   │
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── resume.py        # forge resume
│   │   ├── writeback.py     # forge writeback
│   │   ├── detect.py        # forge detect
│   │   └── transcript.py    # transcript.jsonl 파서
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── qvalue.py        # EMA 업데이트, 감쇠, 초기값
│   │   ├── matcher.py       # stderr→패턴 매칭/제안 (P1)
│   │   ├── promote.py       # 전역 승격, knowledge 승격
│   │   └── context.py       # L0/L1/Rules 포맷 빌더
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── db.py            # 연결, 초기화, 마이그레이션
│   │   ├── models.py        # dataclass (Failure, Decision, Rule, Knowledge, Session)
│   │   └── queries.py       # CRUD 함수
│   │
│   └── hooks/
│       ├── __init__.py
│       ├── install.py       # settings.json 패치
│       └── templates/
│           ├── resume.sh
│           ├── writeback.sh
│           └── detect.sh
│
├── tests/
│   ├── conftest.py          # 공통 fixture (in-memory DB 등)
│   ├── test_qvalue.py
│   ├── test_matcher.py
│   ├── test_context.py
│   ├── test_promote.py
│   ├── test_resume.py
│   ├── test_writeback.py
│   └── fixtures/
│       └── sample_transcript.jsonl
│
├── pyproject.toml
├── README.md
├── CLAUDE.md
└── docs/
    ├── IDEA_NOTES.md
    ├── prd/
    ├── architecture/
    └── trd/
```

---

## 3. 모듈별 인터페이스

### 3.1 config.py

```python
@dataclass
class ForgeConfig:
    # context
    max_tokens: int = 3000
    l0_max_entries: int = 50
    l1_project_entries: int = 3
    l1_global_entries: int = 2
    rules_max_entries: int = 10
    # learning
    alpha: float = 0.1
    decay_daily: float = 0.005
    q_min: float = 0.05
    promote_threshold: int = 2
    knowledge_promote_q: float = 0.8
    knowledge_promote_helped: int = 5
    # initial_q
    initial_q_near_miss: float = 0.6
    initial_q_preventable: float = 0.5
    initial_q_environmental: float = 0.3
    initial_q_decision: float = 0.5
    initial_q_knowledge: float = 0.5

def load_config(path: Path = None) -> ForgeConfig:
    """~/.forge/config.yml 로드. 없으면 기본값."""
```

### 3.2 storage/models.py

```python
@dataclass
class Failure:
    id: int | None
    workspace_id: str
    pattern: str
    observed_error: str | None
    likely_cause: str | None
    avoid_hint: str
    hint_quality: str          # near_miss | preventable | environmental
    q: float
    times_seen: int
    times_helped: int
    times_warned: int
    tags: list[str]
    projects_seen: list[str]
    source: str                # auto | manual | organic
    review_flag: bool
    last_used: datetime | None
    created_at: datetime
    updated_at: datetime

@dataclass
class Decision:
    id: int | None
    workspace_id: str
    statement: str
    rationale: str | None
    alternatives: list[str]
    q: float
    status: str                # active | superseded | revisiting
    superseded_by: int | None
    tags: list[str]
    last_used: datetime | None
    created_at: datetime
    updated_at: datetime

@dataclass
class Rule:
    id: int | None
    workspace_id: str
    rule_text: str
    scope: str | None
    enforcement_mode: str      # block | warn | log
    active: bool
    created_at: datetime

@dataclass
class Knowledge:
    id: int | None
    workspace_id: str
    title: str
    content: str
    source: str                # seeded | organic
    q: float
    tags: list[str]
    promoted_from: int | None
    last_used: datetime | None
    created_at: datetime

@dataclass
class Session:
    id: int | None
    session_id: str
    workspace_id: str
    warnings_injected: list[str]  # failure pattern 목록
    started_at: datetime
    ended_at: datetime | None
```

### 3.3 storage/queries.py

```python
# Failure CRUD
def insert_failure(db, failure: Failure) -> int
def get_failure_by_pattern(db, workspace_id: str, pattern: str) -> Failure | None
def list_failures(db, workspace_id: str, sort_by: str = "q", include_global: bool = True) -> list[Failure]
def update_failure(db, failure: Failure) -> None
def search_by_tags(db, workspace_id: str, tags: list[str]) -> list[Failure]

# Decision CRUD
def insert_decision(db, decision: Decision) -> int
def list_decisions(db, workspace_id: str, status: str = "active") -> list[Decision]
def update_decision(db, decision: Decision) -> None

# Rule CRUD
def insert_rule(db, rule: Rule) -> int
def list_rules(db, workspace_id: str) -> list[Rule]
def update_rule(db, rule: Rule) -> None

# Knowledge CRUD
def insert_knowledge(db, knowledge: Knowledge) -> int
def list_knowledge(db, workspace_id: str, include_global: bool = True) -> list[Knowledge]

# Session
def insert_session(db, session: Session) -> int
def get_session(db, session_id: str) -> Session | None
def update_session_end(db, session_id: str) -> None
```

### 3.4 core/qvalue.py

```python
def ema_update(q: float, reward: float, alpha: float) -> float
    """Q ← Q + α(r - Q)"""

def time_decay(q: float, days: float, decay_rate: float, q_min: float) -> float
    """Q *= (1 - decay) ^ days, 최소 q_min"""

def initial_q(hint_quality: str, config: ForgeConfig) -> float
    """hint_quality → 초기 Q값 매핑"""
```

### 3.5 core/matcher.py

```python
def match_pattern(stderr: str, workspace_id: str, db) -> Failure | None
    """stderr를 기존 패턴과 exact match"""

def suggest_pattern_name(stderr: str) -> str
    """stderr에서 패턴명 자동 제안"""

def extract_errors_from_stderr(stderr: str) -> list[str]
    """stderr에서 에러 클래스/메시지 추출 (regex)"""
```

### 3.6 core/context.py

```python
def build_context(failures: list[Failure], rules: list[Rule], config: ForgeConfig,
                  decisions: list[Decision] | None = None,
                  knowledge_list: list[Knowledge] | None = None) -> str
    """L0 + L1 + Decisions + Knowledge + Rules → 포맷된 문자열 반환"""

def format_l0(failures: list[Failure]) -> str
def format_l1(failures: list[Failure]) -> str
def format_rules(rules: list[Rule]) -> str
def format_decisions(decisions: list[Decision]) -> str
def format_knowledge(knowledge_list: list[Knowledge]) -> str
```

### 3.7 core/promote.py

```python
def check_global_promote(failure: Failure, config: ForgeConfig) -> bool
def promote_to_global(failure: Failure) -> Failure
    """Returns new Failure with workspace_id='__global__'. Caller inserts to DB."""
def check_knowledge_promote(failure: Failure, config: ForgeConfig) -> bool
def promote_to_knowledge(failure: Failure) -> Knowledge
    """Returns Knowledge. Caller inserts to DB."""
def merge_q(failures: list[Failure]) -> float
    """Weighted average of Q values by times_seen."""
```

### 3.8 engines/transcript.py

```python
@dataclass
class BashFailure:
    command: str
    exit_code: int
    stderr: str
    stdout: str

def parse_transcript(path: Path) -> list[BashFailure]
    """transcript.jsonl → 실패한 Bash 결과 목록 (방어적 파싱)"""
```

### 3.9 engines/resume.py

```python
def run_resume(workspace_id: str, session_id: str, db, config: ForgeConfig) -> str
    """context 생성 + session 기록 + 포맷된 문자열 반환"""
```

### 3.10 engines/writeback.py

```python
def run_writeback(workspace_id: str, session_id: str, transcript_path: Path, db, config: ForgeConfig) -> None
    """transcript 파싱 → 패턴 매칭 → Q 갱신 → 감쇠 → 승격 (단일 트랜잭션)"""
```

### 3.11 engines/detect.py

```python
def run_detect(tool_name: str, tool_response: dict, workspace_id: str, db) -> dict | None
    """Bash 실패 감지 → 기존 패턴 매칭 → additionalContext JSON 또는 None"""
```

---

## 4. CLI 명령 매핑

```
forge init                                    → storage/db.py (DB 초기화)
forge record failure --pattern --hint ...     → core/qvalue.py + storage/queries.py
forge record decision --statement ...         → storage/queries.py
forge record rule --text --mode ...           → storage/queries.py
forge record knowledge --title --content ...  → storage/queries.py
forge list --workspace --type --sort          → storage/queries.py
forge search --tag --workspace                → storage/queries.py
forge detail <pattern>                        → storage/queries.py
forge edit <id> --hint/--rationale            → storage/queries.py
forge promote <id> [--to knowledge]           → core/promote.py + storage/queries.py
forge stats                                   → core/qvalue.py + storage/queries.py
forge decay --dry-run                         → core/qvalue.py
forge resume --workspace                      → engines/resume.py (hook용)
forge writeback --workspace --transcript      → engines/writeback.py (hook용)
forge detect --workspace                      → engines/detect.py (hook용)
forge install-hooks                           → hooks/install.py
```

---

## 5. Hook 스크립트 템플릿

### resume.sh

```bash
#!/bin/bash
INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))")
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))")
forge resume --workspace "$WORKSPACE" --session-id "$SESSION_ID"
```

### writeback.sh

```bash
#!/bin/bash
INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))")
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))")
TRANSCRIPT=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('transcript_path',''))")
forge writeback --workspace "$WORKSPACE" --session-id "$SESSION_ID" --transcript "$TRANSCRIPT"
```

### detect.sh

```bash
#!/bin/bash
INPUT=$(cat)
WORKSPACE=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))")
forge detect --workspace "$WORKSPACE" <<< "$INPUT"
```

---

## 6. 테스트 전략

| 대상 | 방식 | 핵심 케이스 |
|------|------|------------|
| qvalue | 단위 | EMA 수렴, 감쇠 최소값, 초기값 매핑 |
| matcher | 단위 | 패턴명 제안, exact match, 에러 추출 |
| context | 단위 | L0/L1 포맷, 토큰 예산 잘라내기, 빈 DB |
| promote | 단위 | 전역 승격 조건, knowledge 승격 조건, Q 병합 |
| resume | 통합 | 빈 DB → 데이터 있는 DB → context 출력 검증 |
| writeback | 통합 | transcript 파싱 → Q 갱신 → 트랜잭션 롤백 |
| DB | in-memory SQLite fixture 사용 |

---

## 7. Silo 구분 (팀 스폰용)

### Silo A: Storage + Config (Foundation)

```
담당 파일:
  forge/config.py
  forge/storage/db.py
  forge/storage/models.py
  forge/storage/queries.py
  tests/conftest.py (DB fixture)
  pyproject.toml
  CLAUDE.md

산출물:
  - ~/.forge/forge.db 생성/마이그레이션
  - config.yml 로딩 + 기본값
  - 5개 테이블 CRUD 전부
  - forge init 명령
```

### Silo B: Core Services

```
담당 파일:
  forge/core/qvalue.py
  forge/core/matcher.py
  forge/core/promote.py
  forge/core/context.py
  tests/test_qvalue.py
  tests/test_matcher.py
  tests/test_context.py
  tests/test_promote.py

산출물:
  - EMA 업데이트, 감쇠, 초기값
  - stderr → 패턴 매칭/제안
  - 전역/knowledge 승격
  - L0/L1/Rules 포맷 빌더
  - 전부 단위 테스트
```

### Silo C: Engines + CLI + Hooks

```
담당 파일:
  forge/cli.py
  forge/engines/resume.py
  forge/engines/writeback.py
  forge/engines/detect.py
  forge/engines/transcript.py
  forge/hooks/install.py
  forge/hooks/templates/*.sh
  tests/test_resume.py
  tests/test_writeback.py
  tests/fixtures/sample_transcript.jsonl

산출물:
  - Typer CLI 전체 (모든 명령)
  - resume/writeback/detect 엔진
  - transcript 파서
  - hook 설치 스크립트
  - 통합 테스트

의존:
  - Silo A (storage)
  - Silo B (core)
```

### 실행 순서

```
Wave 1 (병렬): Silo A + Silo B
Wave 2 (순차): Silo C (A, B 완료 후)
```
