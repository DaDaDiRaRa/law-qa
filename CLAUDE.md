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
- **Frontend**: React + Vite + Tailwind CSS v3, port 5174
- **DB**: `backend/data/law_qa.db` (SQLite + FTS5)
- **AI**: Anthropic Claude API (`claude-sonnet-4-6`, temperature=0)

---

## 실행

```powershell
# start.bat 더블클릭 또는:
cd backend && python main.py          # 백엔드 (port 8001)
cd frontend && npm run dev            # 프론트엔드 (port 5174)
```

브라우저: `http://localhost:5174` — 앱 진입 시 "기본 프로젝트" 자동 생성 후 채팅창 즉시 노출.

---

## DB 스키마

```sql
-- 법령 원문
CREATE TABLE laws (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,        -- 법령명 (예: 건축법 시행령)
    article_no  TEXT,                 -- 조문번호 (예: 제56조(건폐율))
    content     TEXT NOT NULL,        -- 조문 원문
    law_type    TEXT,                 -- 아래 4종 참고
    source      TEXT,                 -- 출처 (법제처 MST 또는 파일명)
    fetched_at  TEXT NOT NULL
);

-- law_type 값
-- 'statute'       : 국가법령 (건축법, 국토계획법 등) — fetch_laws.py
-- 'ordinance'     : 자치법규 (시도 조례) — fetch_ordinances.py
-- 'supplementary' : 부수법령 (소방시설법, 장애인편의법 등) — fetch_supplementary.py
-- 'standard'      : 수치 기준 (zone_limits.json 등 시드 JSON) — seed_laws.py

CREATE VIRTUAL TABLE laws_fts USING fts5(
    title, article_no, content,
    content='laws', content_rowid='id'
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
    source_law_ids  TEXT,           -- 근거 조문 ID 목록 (JSON 배열)
    has_image       INTEGER DEFAULT 0,
    confidence      INTEGER,        -- 1~5 (현재 미사용, NULL)
    created_at      TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE VIRTUAL TABLE query_history_fts USING fts5(
    question, answer,
    content='query_history', content_rowid='id'
);
```

---

## RAG 파이프라인 (query_engine.py)

```
질문 입력
  → 주소 패턴 감지 (r'[가-힣]+[시구군]\s*[가-힣]+[동읍면로길]')
      - 감지되면 land_info.get_land_info() 호출
      - 반환된 zone_use를 FTS 검색 키워드에 추가
      - [대지 정보] 블록을 LLM 프롬프트에 삽입
  → _normalize(): 텍스트 전처리
      - 지자체명 축약 정규화 (서울시·서울 →서울특별시, 경기→경기도 등)
      - 법령 용어 정규화 (건폐→건폐율, 용적→용적률, ZEB/zeb→제로에너지건축물)
  → _tokenize(): 토큰 추출
      - 용도지역 복합어 선추출 (일반상업지역 등 21종, 분리 방지)
      - 공백/구두점 분리 + 한국어 조사 제거 변형 추가
      - 동의어 확장 (건폐율↔건축면적비율, 용적률↔연면적비율, ZEB↔제로에너지건축물, 녹건↔녹색건축)
  → FTS5 AND 검색 → 결과 없으면 OR 검색 (상위 5개)
  → 조문 없음: Claude API 호출 없이 즉시 반환
      - 질문에 힌트 키워드 포함 시: "관련 키워드로 다시 질문해보세요: ..." 제안
      - 힌트 없으면: "현재 DB에서 확인 불가"
  → 조문 있음: 조문 + 질문 → Claude API (temperature=0)
      - 대지 정보 있으면 시스템 프롬프트에 "해당 용도지역 기준 우선 적용" 지시
      - 답변에 "확인 불가" 포함 시 source_law_ids 빈 배열로 반환
      - 답변 하단 면책 문구 자동 추가
      - 수치는 조문 원문 그대로 인용, LLM 재해석 금지
```

힌트 키워드 맵 (`_HINT_MAP`):
- 주차 → 주차장, 주차 기준, 주차 대수
- 높이 → 가로구역, 일조권, 사선제한
- 조경 → 조경 의무, 식재 기준, 대지면적
- 에너지 → 에너지절약계획서, ZEB, 녹색건축
- 용적률 → 용적률 완화, 녹색건축 인증, 공개공지

---

## 대지 정보 서비스 (land_info.py)

주소 문자열 → 용도지역·지구·구역 자동 조회.

```
주소 입력
  → 카카오 로컬 API: 주소 → 위경도 + 법정동코드
  → LURIS 행위제한 API: 필지코드(PNU) → 용도지역·지구·구역
  → 반환: { address, pnu, lat, lng, zone_use, zone_district, zone_area, source }
```

오류 시 각 단계별 한국어 에러메시지 반환. 실패해도 query_engine 기본 흐름 유지.

---

## 환경 변수 (.env)

```
ANTHROPIC_API_KEY=sk-ant-...    # 필수
LAW_API_KEY=...                 # 법제처 DRF API
KAKAO_API_KEY=...               # 카카오 로컬 API (주소→좌표)
LURIS_API_KEY=...               # LURIS 행위제한 API (용도지역 조회)
VWORLD_API_KEY=...              # VWorld (공간정보, 필요 시)
TOJI_API_KEY=...                # 토지이음 API (토지이용계획)
ROAD_API_KEY=...                # 행안부 도로명주소 API
DB_PATH=./data/law_qa.db
```

---

## 법령 데이터 소스

### 시드 데이터 (seed_data/ → seed_laws.py --commit)

**텍스트 파일** — `제N조(제목)` 패턴으로 조문 단위 파싱, `law_type='statute'`

| 파일 | 내용 |
|---|---|
| `law_extracted.txt` | 녹색건축물 조성 지원법 (법·시행령·시행규칙) |
| `law_file0.txt` | 건축물의 에너지절약설계기준 |
| `law_file1.txt` | 재활용 건축자재의 활용기준 |

**JSON 파일** — 수치 데이터를 자연어 문장으로 변환, `law_type='standard'`

| 파일 | 내용 |
|---|---|
| `zone_limits.json` | 용도지역별 건폐율·용적률 시행령 기본값 |
| `parking_standards.json` | 용도·규모별 주차 기준 |
| `landscape_standards.json` | 용도지역별 조경 기준 |
| `far_relief_rules.json` | 용적률 완화 규칙 (녹색건축·ZEB 등) |
| `street_block_heights.json` | 가로구역별 높이 기준 |
| `ordinance_seed.json` | 서울 도시계획조례 §54·§55 수치 |

### API 수집 스크립트 (법제처 DRF API, LAW_API_KEY 필요)

| 스크립트 | 대상 | law_type |
|---|---|---|
| `fetch_laws.py` | 건축법·시행령·시행규칙, 국토계획법·시행령, 주차장법·시행령 (7개) | statute |
| `fetch_ordinances.py` | 17개 광역시·도 × 4개 조례 패턴 (도시계획/건축/주차장/건축위원회) | ordinance |
| `fetch_supplementary.py` | 소방시설법, 장애인편의법, 산지관리법, 도로법 등 부수법령 21개 | supplementary |

```powershell
# 각 스크립트 실행 방법 (backend/ 디렉토리에서)
python -m scripts.seed_laws --dry-run
python -m scripts.seed_laws --commit

python -m scripts.fetch_laws --dry-run
python -m scripts.fetch_laws --commit

python -m scripts.fetch_ordinances --dry-run
python -m scripts.fetch_ordinances --sido 서울특별시 --commit   # 특정 시도만
python -m scripts.fetch_ordinances --commit

python -m scripts.fetch_supplementary --dry-run
python -m scripts.fetch_supplementary --commit
```

---

## 프로젝트 구조 (현재)

```
law-qa/
├── CLAUDE.md
├── .env
├── start.bat                       ← 백엔드·프론트 동시 실행
├── seed_data/
│   ├── law_extracted.txt
│   ├── law_file0.txt
│   ├── law_file1.txt
│   ├── zone_limits.json
│   ├── parking_standards.json
│   ├── landscape_standards.json
│   ├── far_relief_rules.json
│   ├── street_block_heights.json
│   └── ordinance_seed.json
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── data/
│   │   └── law_qa.db
│   ├── scripts/
│   │   ├── seed_laws.py            ← 시드 데이터 적재
│   │   ├── fetch_laws.py           ← 국가법령 수집 (법제처 API)
│   │   ├── fetch_ordinances.py     ← 자치법규 수집 (법제처 API)
│   │   ├── fetch_supplementary.py  ← 부수법령 수집 (법제처 API)
│   │   └── test_query.py           ← 환각 검증 (5개 질문)
│   └── services/
│       ├── db_manager.py
│       ├── query_engine.py         ← RAG + 주소 감지 + 대지정보 연동
│       ├── land_info.py            ← 카카오 + LURIS 주소→용도지역 조회
│       ├── project_manager.py
│       └── history_manager.py
└── frontend/
    ├── package.json
    ├── vite.config.js              ← port 5174, /api 프록시
    └── src/
        ├── App.jsx                 ← 기본 프로젝트 자동 생성, 뷰 라우팅
        └── components/
            ├── ProjectList/        ← 프로젝트 CRUD
            ├── ChatWindow/         ← 채팅 + 프로젝트 전환 드롭다운 + 출처 조문 토글
            └── HistorySearch/      ← 키워드 검색
```

---

## 프론트엔드 동작

- **앱 진입**: `GET /api/projects` → "기본 프로젝트" 없으면 자동 생성 → 채팅창 즉시 표시
- **네비게이션**: 질의 / 프로젝트 관리 / 히스토리 검색 (3탭)
- **ChatWindow 서브 헤더**: 프로젝트 전환 드롭다운 (`/api/projects` 목록)
- **출처 조문**: `[법령명 / 조문번호]` 클릭 → 조문 본문 토글 표시
- **확인 불가 답변**: source_law_ids 빈 배열 → 조문 뱃지 미표시
- **히스토리 로드**: 출처 조문 미표시 (ID만 저장, 전문 미보존)

---

## 다음 개발 단계 (로드맵)

### 완료
- [x] 기본 RAG QA 파이프라인
- [x] 프로젝트/히스토리 관리
- [x] 출처 조문 토글 표시
- [x] 기본 프로젝트 자동 생성 (빠른 질의 모드)
- [x] FTS 검색 품질 개선 (정규화·동의어·복합어)
- [x] 확인 불가 시 힌트 키워드 제안
- [x] 법제처 API 수집 스크립트 3종
- [x] 주소 감지 + LURIS 용도지역 자동 조회 (land_info.py)

---

### Phase 1 — 주소 기반 대지 조회 완성 ✓

- [x] `GET /api/land-info?address=...` 엔드포인트 main.py에 추가
- [x] ChatWindow 입력 영역에 주소 입력 필드 추가
      - 선택 입력 (비워도 기존 채팅 동작)
      - 주소 입력 시 → 자동으로 용도지역 조회 → 채팅창에 "[대지 정보] 제2종일반주거지역" 표시
      - 이후 질문은 해당 용도지역 컨텍스트를 자동 포함해서 전송

---

### Phase 2 — 법규 종합 검토 (compliance_report)

- [ ] `POST /api/compliance` 엔드포인트 추가
      입력: { address, building_use, total_floor_area, floors }
      출력: 건폐율·용적률·주차·높이·조경 5개 항목 종합 검토 결과
- [ ] 백엔드 services/compliance_engine.py 신규 작성
      각 항목별로 FTS 검색 + 조문 근거 포함해서 반환
- [ ] 프론트 종합검토 전용 뷰 추가 (탭 4번째)
      폼 입력 방식 (채팅이 아닌 구조화된 입력)
      결과는 항목별 카드로 표시, 각 카드에 근거 조문 토글

---

### Phase 3 — 데이터 보강

- [ ] 시군구 단위 조례 추가 수집
      광역시·도 아래 주요 시군구 (서울 25개 자치구 우선)
- [ ] 법제처 판례·해석례 API 연동
      `fetch_precedents.py` 스크립트 추가, law_type='precedent'
- [ ] 세움터 API 연동 (건축행정시스템)
      기존 건물 허가 이력·현황 조회 → 증축 검토 시 활용

---

### Phase 4 — MCP 서버화

- [ ] `mcp_server/` 디렉토리 신규 생성
- [ ] MCP SDK (Python) 로 law-qa 백엔드를 MCP 서버로 감싸기
- [ ] 노출할 툴 목록:
      - `search_laws`: 자연어 법령 검색
      - `get_land_info`: 주소 → 용도지역 조회
      - `check_far_coverage`: 건폐율·용적률 검토
      - `check_parking`: 주차 기준 검토
      - `check_height`: 높이 제한 검토
      - `compliance_report`: 종합 검토
- [ ] Claude Code에서 MCP 서버 연결 후 직접 법규 검토 도구로 사용 검증

---

## 코딩 규칙

- temperature=0 고정
- 조문 없으면 LLM 호출 자체를 하지 않음
- 모든 답변에 근거 조문 출처 포함
- 답변 하단 면책 문구: "참고용 정보입니다. 실제 인허가는 담당 건축사 확인 필수"
- 로그는 한국어
