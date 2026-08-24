# law-qa MCP 서버 — 독립 Cloud Run 서비스 (인간용 REST API 는 여전히 로컬 전용,
# kunwon-ops docs/plan-mcp-gateway.md §10 참조: project_manager·history_manager 는
# 쓰기 작업이라 멀티 인스턴스 배포와 안 맞음. MCP 도구 3개는 전부 읽기 전용이라
# 이 부분만 별도로 배포한다 — backend/services/{query_engine,land_info,compliance_engine}.py
# 와 그 셋이 공유하는 db_manager.py, 그리고 읽기 전용 SQLite DB 만 넣는다.
#
# 빌드:  gcloud run deploy law-qa-mcp --source . --region asia-northeast3
FROM python:3.11-slim
WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# services/ 전체를 넣는다(개별 파일만 골라 넣으면 새 함수 추가 시 조용히 깨진다).
# project_manager·history_manager 도 같이 들어오지만 MCP 도구는 그 둘을 안 부른다 —
# import 되지 않으니 죽은 코드로만 남는다.
COPY backend/services/ ./backend/services/
COPY backend/data/law_qa.db ./backend/data/law_qa.db

COPY mcp_server/server.py ./mcp_server/server.py

ENV MCP_TRANSPORT=streamable-http
ENV PORT=8080

CMD ["python", "mcp_server/server.py"]
