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
-- 'precedent'     : 법령해석례·판례 (법제처 DRF expc·prec) — fetch_precedents.py

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
  → _normalize() 후 주소 패턴 감지 (r'[가-힣]+[시구군]\s*[가-힣]+[동읍면로길]')
      - 정규화 먼저: "서울시" → "서울특별시" 변환 후 패턴 매칭
      - _SIDO_RE로 매치 앞 텍스트에서 시/도 접두어 역탐색 → addr_for_lookup 구성
        예: "서울특별시" + "영등포구 당산동" + "3가 385" = "서울특별시 영등포구 당산동3가 385"
      - _BUNJI_RE: r'^[\d\-가나다라호]+(?:\s+\d+(?:-\d+)?)?' — "3가 385" 패턴 지원
      - land_info.get_land_info(addr_for_lookup) 호출
      - zone_use 반환 시: FTS 검색 키워드 + [대지 정보] 블록 LLM 프롬프트에 삽입
      - zone_use 미반환(API 실패) + 기본정보 성격 질문 시:
          → LLM 호출 없이 즉시 "용도지역 직접 포함해서 재질문" 안내 반환
  → _normalize(): 텍스트 전처리
      - 지자체명 축약 정규화 (서울시·서울 → 서울특별시, 경기 → 경기도 등)
      - 법령 용어 정규화 (건폐→건폐율, 용적→용적률, ZEB/zeb→제로에너지건축물)
  → _tokenize(): 토큰 추출
      - 용도지역 복합어 선추출 (일반상업지역 등 21종, 분리 방지)
      - 공백/구두점 분리 + 한국어 조사 제거 변형 추가
      - 동의어 확장 (건폐율↔건축면적비율, 용적률↔연면적비율, ZEB↔제로에너지건축물, 녹건↔녹색건축)
  → 기본정보 성격 질문 감지 시 (_BASIC_QUERY_KW: 기본·정보·알려·검토·어때·얼마·가능)
      → _ZONE_EXTRA_KW(건폐율·용적률·주차·높이·조경) FTS 토큰 자동 추가 (zone_use 여부와 무관)
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

LLM 시스템 프롬프트 (`_SYSTEM`) 특이사항:

- 페르소나: "건축법규를 잘 아는 선배 건축사" — 같은 사무소 동료에게 설명하듯 대화체
- 규칙 4: 조문 없으면 "현재 DB에서 확인 불가" 문장만 출력, 추가 설명·표·목록 일절 금지
- 규칙 6: 조문 밖 정보(추천·외부 기관 연락처 등) 어떤 경우에도 추가 금지
- 말투: 마크다운 표·제목·불릿 과용 금지, 핵심 수치만 굵게, 딱딱한 보고서체 지양

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
  → 카카오 로컬 API: 주소 → 위경도 + 법정동코드 + PNU
  → LURIS 행위제한 API: PNU → 용도지역·지구·구역
  → 반환: { address, pnu, lat, lng, zone_use, zone_district, zone_area, source }
```

오류 시 각 단계별 한국어 에러메시지 반환. 실패해도 query_engine 기본 흐름 유지.

> ⚠️ **현재 알려진 이슈 (2026-06-02 기준) — 용도지역 자동 조회 불가**
>
> **조사 완료된 API 현황:**
>
> | API | 상태 | 원인 |
> |---|---|---|
> | `LURIS_API_KEY` (`luris.molit.go.kr`) | ❌ 403 Forbidden | 서버 측 IP 차단 또는 키 만료. SSL 우회(`_SSL_CTX`) 적용됨 |
> | `VWORLD_API_KEY` — 검색(search) | ✅ 정상 | 개발키에 검색 서비스 등록됨 |
> | `VWORLD_API_KEY` — WFS/WMS/데이터 | ❌ INCORRECT_KEY | 개발키(테스트키)는 search만 허용. WFS·req/data는 운영키 필요 |
> | `arLandUseInfoService` (data.go.kr/1613000) | ✅ API 연결 정상 | 단, 용도지역코드를 입력받아 행위제한 반환하는 API — 주소→용도지역 역방향 조회 불가 |
> | data.go.kr 1611000 WFS | ❌ HTTP 500 | 서비스 자체 오류 |
>
> **진행 중인 해결:**
>
> VWorld **운영키 신청 완료** (2026-06-02 신청, 2026-06-11 기준 승인 미확인). 승인 후 WFS·2D데이터 API 사용 가능.
> → 승인되면 `land_info.py`에 VWorld `req/data` 연동 즉시 구현:
> ```
> GET https://api.vworld.kr/req/data
>   ?service=data&version=2.0&request=GetFeature
>   &data=LT_C_UQ111&geomFilter=POINT({lng} {lat})
>   &format=json&size=1&key=VWORLD_API_KEY
> ```
> 응답의 `prposArea` 필드 → `zone_use` 매핑.
>
> **대기 중 병행 시도:**
> data.go.kr "토지특성정보서비스" — LURIS_API_KEY(기존 키)로 PNU → 용도지역 조회 가능 여부 미확인. 테스트 예정.
>
> **현재 폴백:** query_engine이 zone_use 없을 때 "용도지역을 직접 포함해서 재질문" 안내 반환.

---

## 환경 변수 (.env)

```
ANTHROPIC_API_KEY=sk-ant-...    # 필수
LAW_API_KEY=...                 # 법제처 DRF API
KAKAO_API_KEY=...               # 카카오 로컬 API (주소→좌표) — 정상 작동
LURIS_API_KEY=...               # data.go.kr 서비스키 — arLandUseInfoService 작동, luris.molit.go.kr는 IP 차단
EUM_KEY=...                     # 토지이음 직접 API 키 — luris.molit.go.kr IP 차단으로 사용 불가 (GET/POST 모두 Error403.jsp로 리다이렉트)
VWORLD_API_KEY=...              # VWorld — ⚠️ 운영키 심사 중 (2026-06-02 신청). 승인 후 WFS·데이터 API 사용 가능
ROAD_API_KEY=...                # 행안부 도로명주소 API (미설정)
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

| 스크립트 | 대상 | law_type | 수집 여부 |
|---|---|---|---|
| `fetch_laws.py` | 건축법·시행령·시행규칙, 국토계획법·시행령, 주차장법·시행령 (7개) | statute | ✅ 917건 적재 |
| `fetch_ordinances.py` | 17개 광역시·도 × 4개 조례 패턴 (도시계획/건축/주차장/건축위원회) | ordinance | ✅ 1,393건 적재 |
| `fetch_ordinances.py --sigungu` | 서울 25개 자치구 주차장 조례 | ordinance | ✅ 991건 적재 |
| `fetch_supplementary.py` | 소방시설법, 장애인편의법, 산지관리법, 도로법 등 부수법령 21개 | supplementary | ✅ 1,345건 적재 |
| `fetch_precedents.py` | 건축법 등 관련 법령해석례(expc) + 판례(prec) 4개 키워드 | precedent | ✅ 939건 적재 |

```powershell
# 각 스크립트 실행 방법 (backend/ 디렉토리에서)
python -m scripts.seed_laws --dry-run
python -m scripts.seed_laws --commit

python -m scripts.fetch_laws --dry-run
python -m scripts.fetch_laws --commit                            # 핵심 국가법령 (917건 적재 완료)

python -m scripts.fetch_ordinances --dry-run
python -m scripts.fetch_ordinances --sido 서울특별시 --commit   # 특정 시도만
python -m scripts.fetch_ordinances --commit                     # 광역시·도 전체 (1,393건 적재 완료)

python -m scripts.fetch_ordinances --sigungu 서울특별시 --dry-run
python -m scripts.fetch_ordinances --sigungu 서울특별시 --commit  # 시군구 단위 (서울 991건 적재 완료)

python -m scripts.fetch_supplementary --dry-run
python -m scripts.fetch_supplementary --commit                  # 부수법령 (1,345건 적재 완료)

python -m scripts.fetch_precedents --dry-run
python -m scripts.fetch_precedents --commit                     # 법령해석례·판례 (939건 적재 완료)
```

### 현재 DB 적재 현황 (2026-06-11 기준)

| law_type | 건수 | 내용 |
|---|---|---|
| statute | 1,165건 | 건축법·시행령·시행규칙, 국토계획법·시행령, 주차장법·시행령, 녹색건축물법 등 |
| ordinance | 2,384건 | 17개 광역시·도 조례 + 서울 25개 자치구 주차장 조례 |
| supplementary | 1,345건 | 소방시설법, 장애인편의법, 산지관리법, 도로법 등 |
| standard | 305건 | 시드 JSON (건폐율·용적률·주차·조경·높이 수치 기준) |
| precedent | 939건 | 건축법 관련 법령해석례(expc) + 판례(prec) |
| **합계** | **6,138건** | — |

### 데이터 갱신 정책

월 1회 수동 실행. 법령 개정 공지 확인 후 해당 스크립트만 재실행.
재실행 시 기존 행은 `(title, article_no)` 중복 체크로 자동 건너뜀.

---

## 프로젝트 구조 (현재)

```
law-qa/
├── CLAUDE.md
├── .env
├── .mcp.json                       ← Claude Code MCP 서버 등록 (law-qa)
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
├── mcp_server/
│   └── server.py                   ← FastMCP 서버 (search_laws·get_land_info·compliance_report)
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── data/
│   │   └── law_qa.db
│   ├── scripts/
│   │   ├── seed_laws.py            ← 시드 데이터 적재
│   │   ├── fetch_laws.py           ← 국가법령 수집 (법제처 API)
│   │   ├── fetch_ordinances.py     ← 자치법규 수집 (--sigungu 플래그로 시군구 지원)
│   │   ├── fetch_supplementary.py  ← 부수법령 수집 (법제처 API)
│   │   ├── fetch_precedents.py     ← 법령해석례·판례 수집 (법제처 API)
│   │   └── test_query.py           ← 환각 검증 (5개 질문)
│   └── services/
│       ├── db_manager.py
│       ├── query_engine.py         ← RAG + 주소 감지 + 대지정보 연동
│       ├── land_info.py            ← 카카오 + LURIS 주소→용도지역 조회
│       ├── compliance_engine.py    ← 건폐율·용적률·주차·높이·조경 종합 검토
│       ├── project_manager.py
│       └── history_manager.py
└── frontend/
    ├── package.json
    ├── vite.config.js              ← port 5174, /api 프록시
    └── src/
        ├── App.jsx                 ← 기본 프로젝트 자동 생성, 뷰 라우팅 (4탭)
        └── components/
            ├── ProjectList/        ← 프로젝트 CRUD
            ├── ChatWindow/         ← 채팅 + 프로젝트 전환 드롭다운 + 출처 조문 토글
            ├── HistorySearch/      ← 키워드 검색
            └── ComplianceView/     ← 법규 종합 검토 폼 + 항목별 카드 결과
```

---

## 프론트엔드 동작

- **앱 진입**: `GET /api/projects` → "기본 프로젝트" 없으면 자동 생성 → 채팅창 즉시 표시
- **네비게이션**: 질의 / 프로젝트 관리 / 히스토리 검색 / 종합 검토 (4탭)
- **ChatWindow 서브 헤더**: 프로젝트 전환 드롭다운 (`/api/projects` 목록)
- **출처 조문**: `[법령명 / 조문번호]` 클릭 → 조문 본문 토글 표시
- **확인 불가 답변**: source_law_ids 빈 배열 → 조문 뱃지 미표시
- **히스토리 로드**: 출처 조문 미표시 (ID만 저장, 전문 미보존)
- **종합 검토**: 주소·용도·연면적·층수 입력 → 건폐율·용적률·주차·높이·조경 5개 항목 카드 출력

---

## 다음 개발 단계 (로드맵)

### 완료
- [x] 기본 RAG QA 파이프라인
- [x] 프로젝트/히스토리 관리
- [x] 출처 조문 토글 표시
- [x] 기본 프로젝트 자동 생성 (빠른 질의 모드)
- [x] FTS 검색 품질 개선 (정규화·동의어·복합어)
- [x] LLM 답변 말투 개선 — "선배 건축사" 페르소나, 대화체, 확인불가 시 추가설명 금지
- [x] 확인 불가 시 힌트 키워드 제안
- [x] 법제처 API 수집 스크립트 4종 (fetch_laws·fetch_ordinances·fetch_supplementary·fetch_precedents)
- [x] 주소 감지 파이프라인 구축 (land_info.py) — 카카오 → PNU까지 정상, 용도지역 API 대기 중
- [x] VWorld API 조사 — 개발키·운영키 구분 확인, 운영키 신청 완료 (2026-06-02)

---

### Phase 1 — 주소 기반 대지 조회 (부분 완료, 용도지역 API 대기 중)

- [x] `GET /api/land-info?address=...` 엔드포인트 main.py에 추가
- [x] 질문 텍스트 내 주소 패턴 자동 감지 → 용도지역 조회 → FTS 토큰·LLM 프롬프트 자동 반영
      - 별도 입력 필드 없음 — 채팅창에 주소 포함해서 질문하면 자동 처리
      - 예: "강남구 삼성동 부지에 건물 지을건데 건폐율 얼마야?"
- [x] 주소 추출 정확도 개선: 정규화 후 패턴 검색, 시/도 접두어 역탐색, 번지 패턴 확장
- [x] 기본정보 질문 시 건폐율·용적률 등 법규 키워드 FTS 자동 추가
- [x] zone_use 조회 실패 시 LLM 호출 없이 "용도지역 직접 포함해서 재질문" 안내
- [x] VWorld API 조사 완료 — 개발키는 search만 허용, 운영키 필요
- [ ] **[대기] VWorld 운영키 승인 후** → `land_info.py`에 VWorld `req/data` 연동
      승인 확인 후 코드 구현 즉시 가능 (엔드포인트·파라미터 확정됨)
- [ ] **[병행 시도] data.go.kr 토지특성정보서비스** — 기존 LURIS_API_KEY로 PNU → 용도지역 조회 가능 여부 테스트
      가능하면 VWorld 승인 전에도 용도지역 조회 구현 가능

---

### Phase 2 — 법규 종합 검토 (compliance_report) ✓

- [x] `POST /api/compliance` 엔드포인트 추가
      입력: { address, building_use, total_floor_area, floors }
      출력: 건폐율·용적률·주차·높이·조경 5개 항목 종합 검토 결과
- [x] 백엔드 services/compliance_engine.py 신규 작성
      토픽별 FTS 검색 → 단일 Claude API 호출 → ## 헤더 기준 파싱
- [x] 프론트 종합검토 전용 뷰 추가 (탭 4번째)
      폼 입력 방식 (채팅이 아닌 구조화된 입력)
      결과는 항목별 카드로 표시, 각 카드에 근거 조문 토글

---

### Phase 3 — 데이터 보강 (법령·판례 수집 완료, 세움터 연동 대기)

- [x] 시군구 단위 조례 수집 — 서울 25개 자치구 주차장 조례 991건 완료
- [x] 핵심 국가법령 수집 완료 — 건축법·시행령·시행규칙, 국토계획법·시행령, 주차장법·시행령 917건
- [x] 광역시·도 조례 수집 완료 — 17개 시도 1,393건
- [x] 부수법령 수집 완료 — 소방시설법, 장애인편의법 등 1,345건
- [x] 법제처 판례·해석례 API 연동 — `fetch_precedents.py` 완료, law_type='precedent' 939건 적재
- [ ] 세움터 API 연동 (건축행정시스템)
      기존 건물 허가 이력·현황 조회 → 증축 검토 시 활용

---

### Phase 4 — MCP 서버화 ✓

- [x] `mcp_server/server.py` 작성 (FastMCP, stdio 방식)
- [x] 노출 도구 3종:
      - `search_laws`: 자연어 법령 검색 (주소 자동 감지 포함)
      - `get_land_info`: 주소 → 용도지역 조회
      - `compliance_report`: 건폐율·용적률·주차·높이·조경 종합 검토
- [x] backend/services/ 직접 import — 서비스 로직 변경 시 MCP 자동 반영
- [x] `.mcp.json` 프로젝트 루트에 생성 → Claude Code 재시작 시 자동 로드

연결: `.mcp.json`이 프로젝트 루트에 있으므로 Claude Code 재시작만 하면 됨.
설치 필요: `pip install mcp>=1.0.0` (backend/requirements.txt에 포함)

---

## 코딩 규칙

- temperature=0 고정
- 조문 없으면 LLM 호출 자체를 하지 않음
- 모든 답변에 근거 조문 출처 포함
- 답변 하단 면책 문구: "참고용 정보입니다. 실제 인허가는 담당 건축사 확인 필수"
- 로그는 한국어
