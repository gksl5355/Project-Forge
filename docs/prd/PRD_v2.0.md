# Project Forge v2.0 PRD

## 1. 개요

v2는 **외부 리소스 없이 기능을 개선**하는 버전입니다.
(v3에서 sqlite-vec 등 리소스 의존 기능 추가 예정)

---

## 2. 기능 (4개)

### F1. Debate 모드 — 외부 LLM 검토

TO의 debate skill을 Forge 연동 독립 도구로 분리합니다.

**흐름:**
```
forge debate --topic "JWT vs Session Auth" --workspace .
  1. Forge에서 관련 failures/decisions/knowledge 수집 (태그/패턴 매칭)
  2. 제안서(proposal) 자동 생성 (Forge 컨텍스트 포함)
  3. 외부 LLM에 전달 (Codex CLI 또는 Anthropic API)
  4. 비평(critique) 파싱: BLOCK / TRADEOFF / ACCEPT
  5. 결과를 decision으로 forge.db에 저장 (선택)
  6. /tmp/debate-result-{timestamp}.md에 상세 기록
```

**외부 LLM 우선순위:**
1. Codex CLI (`codex exec`) — 설치되어 있으면 사용
2. Anthropic API — config의 anthropic_api_key로 폴백
3. 미설정 시 — 수동 리뷰 모드 (제안서만 출력)

**리스크 스코어링** (TO 방식 유지):
- uncertainty(1-3) + impact(1-3) + complexity(1-3) = 총점/9
- 6-7: 자동 판단 / 8-9 또는 irreversible: 사용자 확인

**새 파일:**
- `forge/engines/debate.py` — debate 엔진
- `forge/skills/debate/SKILL.md` — Claude Code skill 정의 (선택)

**수정 파일:**
- `forge/cli.py` — `forge debate` 명령 추가
- `forge/config.py` — `codex_model`, `debate_max_rounds` 추가

### F2. 컨텍스트 오염 방지 — Scriptable 패턴 학습

LLM 없이 로컬에서 처리 가능한 작업 패턴을 학습합니다.

**개념:**
```
writeback 시 분석:
  "이 도구 호출은 단순 파싱이었다" → knowledge에 scriptable_pattern 기록
  "이 출력은 5000자인데 결론은 pass/fail 한 줄이었다" → 요약 패턴 기록

다음 세션 resume 시:
  "[HINT] 테스트 출력은 pass/fail 요약만 주입하면 충분합니다"
```

**구현:**
- writeback에서 transcript 분석: 도구 출력 크기 vs 실제 활용도
- 큰 출력이 무시된 패턴 → `output_summary_pattern` knowledge 자동 생성
- resume에서 관련 힌트 주입

**새 파일:**
- `forge/core/output_analyzer.py` — 도구 출력 분석기

**수정 파일:**
- `forge/engines/writeback.py` — 출력 분석 단계 추가

### F3. Dedup 주기 자동화

config 기반으로 writeback 시 자동 dedup 트리거합니다.

**구현:**
```yaml
# config.yml
dedup_interval_days: 14    # 0이면 비활성
```

- writeback 끝에 마지막 dedup 시간 확인
- `dedup_interval_days` 경과 시 자동 실행
- 결과 로그 출력

**수정 파일:**
- `forge/config.py` — `dedup_interval_days` 추가
- `forge/engines/writeback.py` — dedup 자동 트리거
- `forge/storage/db.py` — `forge_meta` 테이블 (last_dedup_at 등 메타 저장)

### F4. TO Auto-Ingest

writeback hook에서 자동으로 TO 런 데이터를 수집합니다.

**구현:**
- writeback 완료 후 `.claude/runs/` 디렉토리 존재 확인
- 있으면 `run_ingest_auto()` 비동기 실행
- config에 `auto_ingest_enabled: true` (기본값)

**수정 파일:**
- `forge/engines/writeback.py` — ingest 자동 호출
- `forge/config.py` — `auto_ingest_enabled` 추가

---

## 3. 스키마 변경

```sql
-- forge_meta 테이블 (시스템 메타데이터)
CREATE TABLE IF NOT EXISTS forge_meta (
    key   TEXT PRIMARY KEY,
    value TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

`_migrate()` v3→v4는 불필요 — forge_meta는 `CREATE IF NOT EXISTS`로 처리.

---

## 4. 파일 목록

### 신규
| 파일 | 역할 |
|------|------|
| `forge/engines/debate.py` | debate 엔진 (proposal → critique → decision) |
| `forge/core/output_analyzer.py` | 도구 출력 분석 (scriptable 패턴 학습) |

### 수정
| 파일 | 변경 |
|------|------|
| `forge/cli.py` | `forge debate` 명령 |
| `forge/config.py` | debate/dedup/ingest 설정 |
| `forge/engines/writeback.py` | 출력 분석 + dedup 자동 + auto-ingest |
| `forge/storage/db.py` | forge_meta 테이블 |
| `forge/storage/queries.py` | forge_meta CRUD |

---

## 5. 검증

```bash
# F1
forge debate --topic "SQLite vs PostgreSQL" --workspace .

# F2
forge writeback --workspace . --session-id test --transcript <path>
# → scriptable 패턴이 knowledge에 자동 기록되었는지 확인

# F3
# config에 dedup_interval_days: 0 설정 후 writeback → dedup 안 됨
# dedup_interval_days: 1 설정 후 writeback → 자동 dedup 실행

# F4
# .claude/runs/ 디렉토리에 report.yml 준비 후 writeback → auto-ingest 확인

# 전체
pytest tests/ -v
```
