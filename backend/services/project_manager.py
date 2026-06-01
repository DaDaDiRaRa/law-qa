from datetime import datetime, timezone

from services.db_manager import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict:
    return dict(row) if row else None


def create(name: str, description: str | None = None) -> dict:
    now = _now()
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO projects (name, description, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (name, description, now, now),
        )
        conn.commit()
        return _row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


def get(project_id: int) -> dict | None:
    conn = get_connection()
    try:
        return _row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())
    finally:
        conn.close()


def list_all() -> list[dict]:
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()]
    finally:
        conn.close()


def delete(project_id: int) -> bool:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM query_history WHERE project_id = ?", (project_id,))
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
