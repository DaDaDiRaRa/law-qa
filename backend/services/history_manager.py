import json
import re
from datetime import datetime, timezone

from services.db_manager import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    if not row:
        return None
    d = dict(row)
    if d.get("source_law_ids") and isinstance(d["source_law_ids"], str):
        d["source_law_ids"] = json.loads(d["source_law_ids"])
    return d


def save(
    project_id: int,
    question: str,
    answer: str,
    source_law_ids: list[int] | None = None,
    has_image: bool = False,
    confidence: int | None = None,
) -> dict:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO query_history "
            "(project_id, question, answer, source_law_ids, has_image, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                project_id,
                question,
                answer,
                json.dumps(source_law_ids) if source_law_ids is not None else None,
                1 if has_image else 0,
                confidence,
                _now(),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM query_history WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def get_by_project(project_id: int, limit: int = 50) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM query_history WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def search(query: str, project_id: int | None = None, limit: int = 20) -> list[dict]:
    tokens = [t for t in re.split(r'[\s\?!,.·「」【】\(\)]+', query) if len(t) >= 2]
    if not tokens:
        return []

    conn = get_connection()
    try:
        def _run(fts_q: str) -> list:
            try:
                if project_id is not None:
                    return conn.execute(
                        "SELECT qh.* FROM query_history_fts f "
                        "JOIN query_history qh ON qh.id = f.rowid "
                        "WHERE query_history_fts MATCH ? AND qh.project_id = ? "
                        "ORDER BY rank LIMIT ?",
                        (fts_q, project_id, limit),
                    ).fetchall()
                return conn.execute(
                    "SELECT qh.* FROM query_history_fts f "
                    "JOIN query_history qh ON qh.id = f.rowid "
                    "WHERE query_history_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (fts_q, limit),
                ).fetchall()
            except Exception:
                return []

        rows = _run(" ".join(f'"{t}"' for t in tokens))
        if not rows and len(tokens) > 1:
            rows = _run(" OR ".join(f'"{t}"' for t in tokens))
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
