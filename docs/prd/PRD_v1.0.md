# Project Forge v1.0 PRD

## 1. 개요

Forge v1은 **Forge를 단일 학습 백엔드로 통합**하는 버전입니다.

**핵심 문제**: Forge(경험 학습)와 TO(팀 실행)가 각각 독자적 학습 저장소를 운영 중이며, 두 시스템이 동시에 context를 주입하면 에이전트가 과도한 컨텍스트로 혼란을 겪습니다.

**목표**: TO는 실행만 담당하고, 학습 데이터는 forge.db로 수렴.

---

## 2. 기능 (Features)

### F1. TO 런 데이터 수집 어댑터 (Ingest)

TO의 `.claude/runs/` 아티팩트를 forge.db로 흡수합니다.

- **새 테이블**: `team_runs` — 런 메타데이터 (complexity, team_config, success_rate 등)
- **수집 로직**: `forge/engines/ingest.py`
  - `report.yml` → `team_runs` INSERT
  - `events.yml`의 `scope_drift` → failures INSERT (hint_quality: preventable)
  - `events.yml`의 `retry_heavy` → failures INSERT (hint_quality: near_miss)
  - `events.yml`의 `team_success` → knowledge INSERT (best team config)
- **CLI**: `forge ingest --workspace <path> --run-dir <dir>` 또는 `forge ingest --auto`

### F2. 벡터 검색 — P2 패턴 매칭

P1(exact match)에서 P2(유사도 + Q값 하이브리드)로 진화합니다.

- **임베딩 모델**: `sentence-transformers/all-MiniLM-L6-v2` (384d, 로컬, ~80MB)
- **하이브리드 스코어**: `score = (1-λ) × z(similarity) + λ × z(Q)`, λ=0.5
- **Graceful degradation**: sentence-transformers 미설치 시 P1 폴백
- **CLI**: `forge embed --workspace <path>` — 배치 임베딩 생성

### F3. 컨텍스트 예산 통합 관리

총 4000 토큰 예산으로 Forge + Team context를 통합 관리합니다.

- **배분**: Forge 2500 토큰 / Team 1000 토큰 / 여유 500 토큰
- **중복 제거**: 동일 pattern이 forge와 team 양쪽에 있으면 forge 버전만 출력
- **섹션 분리**: `## Forge Experience` / `## Team History`
- **TO 인터페이스**: `forge resume --team-brief` — 팀 경험 요약만 출력

### F4. LLM 기반 자동 추출

transcript에서 failure/decision을 Claude API로 자동 추출합니다.

- **CLI**: `forge writeback --llm-extract`
- **모델**: Claude Haiku (세션당 ~$0.001)
- **Graceful degradation**: API 키 미설정 시 기존 regex 방식 유지
- **중복 체크**: 기존 패턴과 비교 후 새 패턴만 INSERT

### F5. 중복 병합 (Dedup & Merge)

유사도 80%+ failure를 탐지하고 병합합니다.

- **CLI**: `forge dedup --workspace <path> [--auto]`
- **병합 로직**: Q값 가중 평균, times_seen/helped 합산, 하위 패턴 soft-delete (active=0)

---

## 3. 스키마 v3

v2 → v3 마이그레이션:
- `failures` 테이블에 `active INTEGER DEFAULT 1` 컬럼 추가
- `team_runs` 테이블 신규 생성
- `failure_embeddings` 가상 테이블 (sqlite-vec 확장 존재 시)

---

## 4. 의존성

```toml
[project.optional-dependencies]
vector = ["sqlite-vec>=0.1.0", "sentence-transformers>=2.0"]
llm = ["anthropic>=0.30"]
all = ["sqlite-vec>=0.1.0", "sentence-transformers>=2.0", "anthropic>=0.30"]
```

**핵심 원칙**: vector/llm 미설치 시에도 v0 기능은 100% 동작 (graceful degradation).

---

## 5. 파일 구조

### 신규 파일
| 파일 | 역할 |
|------|------|
| `forge/engines/ingest.py` | TO 런 데이터 수집 |
| `forge/core/embedding.py` | 벡터 임베딩 생성/조회 |
| `forge/core/dedup.py` | 중복 병합 로직 |
| `forge/engines/extractor.py` | LLM 기반 추출 |

### 수정 파일
| 파일 | 변경 |
|------|------|
| `forge/storage/db.py` | v3 마이그레이션 |
| `forge/storage/models.py` | TeamRun dataclass, Failure.active |
| `forge/storage/queries.py` | team_runs CRUD, soft_delete, v0 fixes |
| `forge/core/matcher.py` | match_pattern_v2 |
| `forge/core/context.py` | 통합 context 빌더 |
| `forge/engines/resume.py` | team context 통합 |
| `forge/engines/writeback.py` | LLM 추출 분기 |
| `forge/config.py` | v1 설정 추가 |
| `forge/cli.py` | ingest/embed/dedup 명령 |
| `forge/hooks/install.py` | settings.json 쓰기 오류 처리 |

---

## 6. v0 코드 품질 수정

1. `queries.py`: `_safe_json_loads()` — json.loads 예외처리
2. `queries.py`: `search_by_tags()` — O(N*M) → 단일 SQL 쿼리
3. `cli.py`: 입력 길이 검증 (pattern ≤200, hint ≤2000)
4. `install.py`: settings.json 쓰기 실패 처리

---

## 7. 검증

```bash
pytest tests/ -v   # 622+ 테스트 통과
```
