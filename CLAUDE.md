# law-qa

건축법규 자연어 질의 앱 — 사내 전용.
설계 중 법규가 궁금할 때, 프로젝트 초기 기준 확인할 때, 자연어로 묻고 답을 받는 독립 앱.

---

## 🔴 세션 운영 규칙

1. **추측 금지** — 법령 수치·조문 해석은 DB에 있는 원문 근거가 있을 때만 답변. 없으면 "확인 불가" 반환.
2. **환각 차단 최우선** — 조문 근거 없이 수치를 생성하는 코드 작성 금지.
3. **단순함 우선** — 요청 범위 밖 기능·추상화 추가 금지.
4. **외과적 수정** — 요청된 부분만 수정.

---

## 프로젝트 개요

| 항목 | 내용 |
|---|---|
| 목적 | 건축사가 설계 중 법규를 자연어로 질의하는 앱 |
| 사용자 | 사내 건축사 (신입~시니어) |
| 성격 | 독립 앱 — 기존 arch-law-diagnose와 코드·DB 공유 없음 |
| 배포 | 로컬 서버 |

---

## 기술 스택

- **Backend**: FastAPI (Python 3.12), port 8001
- **Frontend**: React + Vite + Tailwind, port 5174
- **DB**: `./data/law_qa.db` (SQLite + FTS5)
- **AI**: Anthropic Claude API (claude-sonnet-4, temperature=0)

---

## DB 스키마

```sql
-- 법령 원문
CREATE TABLE laws (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,        -- 법령명 (예: 건축법 시행령)
    article_no  TEXT,                 -- 조문번호 (예: 제56조)
    content     TEXT NOT NULL,        -- 조문 원문
    law_type    TEXT,                 -- 'statute' | 'ordinance' | 'guideline'
    source      TEXT,                 -- 출처 (법제처 URL 또는 파일명)
    fetched_at  TEXT NOT NULL
);

CREATE VIRTUAL TABLE laws_fts USING fts5(
    title, article_no, content,
    content='laws',
    content_rowid='id'
);

-- 프로젝트
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- 질의 히스토리
CREATE TABLE query_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT NOT NULL,
    source_law_ids  TEXT,           -- 근거 조문 ID 목록 (JSON)
    has_image       INTEGER DEFAULT 0,
    confidence      INTEGER,        -- 1~5
    created_at      TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE VIRTUAL TABLE query_history_fts USING fts5(
    question, answer,
    content='query_history',
    content_rowid='id'
);
```

---

## RAG 파이프라인 핵심 규칙 (하드코딩)

```
질문 입력
  → FTS5로 관련 조문 검색 (상위 5개)
  → 조문 있음: 조문 + 질문 → Claude API → 답변 (출처 조문 번호 포함 필수)
  → 조문 없음: Claude API 호출하지 않고 "현재 DB에서 확인 불가" 반환
  → 수치 포함 답변: 조문 원문 수치 그대로 인용, LLM 재해석 금지
```

---

## 환경 변수 (.env)

```
ANTHROPIC_API_KEY=sk-ant-...    # 필수
LAW_API_KEY=...                 # 법제처 추가 수집 시 선택
DB_PATH=./data/law_qa.db
```

외부 지도·주소 API 없음 (VWorld, Kakao 불필요).

---

## 법령 데이터 소스

초기 시드 데이터 — `seed_data/` 폴더에 위치. 두 종류로 구분:

### 텍스트 파일 — 조문 단위로 파싱해서 laws 테이블에 적재

| 파일 | 내용 |
|---|---|
| `law_extracted.txt` | 녹색건축물 조성 지원법 (법·시행령·시행규칙) |
| `law_file0.txt` | 건축물의 에너지절약설계기준 |
| `law_file1.txt` | 재활용 건축자재의 활용기준 |

파싱 방식: `=== 파일명 ===` 으로 문서 구분, `제N조(제목)` 패턴으로 조문 단위 분리.

### JSON 파일 — 수치 데이터를 읽기 가능한 텍스트로 변환 후 laws 테이블에 적재

| 파일 | 내용 |
|---|---|
| `zone_limits.json` | 용도지역별 건폐율·용적률 시행령 기본값 |
| `parking_standards.json` | 용도·규모별 주차 기준 |
| `landscape_standards.json` | 용도지역별 조경 기준 |
| `far_relief_rules.json` | 용적률 완화 규칙 (녹색건축·ZEB 등) |
| `street_block_heights.json` | 가로구역별 높이 기준 |
| `ordinance_seed.json` | 서울 도시계획조례 §54·§55 수치 |

변환 방식: JSON 키-값을 "일반상업지역 건폐율 한도: 60%" 같은 자연어 문장으로 변환 후 저장.

### 추가 수집 대상 (법제처 API, 선택)
- 건축법 + 시행령 + 시행규칙
- 국토의 계획 및 이용에 관한 법률 + 시행령
- 주차장법 시행령

---

## 프로젝트 구조 (목표)

```
law-qa/
├── CLAUDE.md
├── .env
├── .env.example
├── seed_data/              ← 법령 원문 텍스트 파일
│   ├── law_extracted.txt
│   ├── law_file0.txt
│   └── law_file1.txt
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── data/
│   │   └── law_qa.db
│   ├── scripts/
│   │   └── seed_laws.py    ← 최우선 작성 대상
│   └── services/
│       ├── db_manager.py
│       ├── query_engine.py
│       ├── project_manager.py
│       ├── history_manager.py
│       └── llm_client.py
└── frontend/
    ├── package.json
    └── src/
        ├── App.jsx
        └── components/
            ├── ProjectList/
            ├── ChatWindow/
            └── HistorySearch/
```

---

## 개발 순서

1. **DB 초기화 + seed_laws.py** — 법령 원문 파싱·적재
2. **query_engine.py** — FTS5 검색 + Claude API 연동
3. **project_manager + history_manager** — 프로젝트·히스토리 CRUD
4. **FastAPI 엔드포인트**
5. **React 프론트엔드**

---

## 코딩 규칙

- temperature=0 고정
- 조문 없으면 LLM 호출 자체를 하지 않음
- 모든 답변에 근거 조문 출처 포함
- 답변 하단 면책 문구: "참고용 정보입니다. 실제 인허가는 담당 건축사 확인 필수"
- 로그는 한국어
