#!/usr/bin/env python3
"""query_engine 환각 여부 확인용 테스트 스크립트.

python -m scripts.test_query
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

sys.stdout.reconfigure(encoding="utf-8")

from services import query_engine as qe

QUESTIONS = [
    # DB에 있는 내용 — 수치 정확도 확인
    ("Q1 건폐율/용적률",
     "일반상업지역의 건폐율 한도와 용적률 한도는?",
     "기대: 건폐율 80%(시행령 기본값) 또는 서울 60%, 용적률 1300% 또는 서울 800%"),

    # DB에 있는 내용 — 주차 기준
    ("Q2 주차 기준",
     "업무시설 주차 대수 기준 알려줘",
     "기대: 시설면적 150㎡당 1대"),

    # DB에 있는 내용 — 법조문 검색
    ("Q3 에너지 절약",
     "에너지절약계획서를 제출하지 않아도 되는 건축물 종류는?",
     "기대: 건축물의 에너지절약설계기준 제3조 관련 내용"),

    # DB에 있는 내용 — 용적률 완화 수치
    ("Q4 ZEB 완화율",
     "제로에너지건축물 ZEB 1등급 인증 시 용적률 완화율은?",
     "기대: 15%"),

    # DB에 없는 내용 — 환각 방지 확인
    ("Q5 없는 정보",
     "방화지구 건폐율 한도는 몇 퍼센트야?",
     "기대: '현재 DB에서 확인 불가' — DB에 방화지구 데이터 없음"),
]

SEP = "─" * 70


def run():
    for label, question, expectation in QUESTIONS:
        print(f"\n{SEP}")
        print(f"[{label}]")
        print(f"질문: {question}")
        print(f"검증 포인트: {expectation}")
        print()

        result = qe.answer(question)

        print(f"▶ 검색된 조문 {len(result['source_laws'])}개:")
        for law in result["source_laws"]:
            print(f"  - [{law['title']} / {law['article_no']}]")
            print(f"    {law['content'][:80]}...")

        print()
        print("▶ 답변:")
        print(result["answer"])

    print(f"\n{SEP}")
    print("테스트 완료")


if __name__ == "__main__":
    run()
