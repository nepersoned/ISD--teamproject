import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(os.getenv("DB_PATH", "lms_copilot.db"))


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema():
    schema_path = Path(__file__).parent / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with get_conn() as conn:
        conn.executescript(sql)
    print(f"[DB] schema applied → {DB_PATH.resolve()}")


# ── User ──────────────────────────────────────────────

def upsert_user(lms_id: str, enc_cookie: str = None, interval: int = 3600) -> int:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO User (lms_id, enc_session_cookie, scraping_interval)
            VALUES (?, ?, ?)
            ON CONFLICT(lms_id) DO UPDATE
              SET enc_session_cookie = excluded.enc_session_cookie,
                  scraping_interval  = excluded.scraping_interval
            """,
            (lms_id, enc_cookie, interval),
        )
        row = conn.execute("SELECT user_id FROM User WHERE lms_id = ?", (lms_id,)).fetchone()
    return row["user_id"]


def touch_sync(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE User SET last_sync_at = datetime('now') WHERE user_id = ?",
            (user_id,),
        )


# ── Course / Enrollment ───────────────────────────────

def upsert_course(lms_url_id: str, course_code: str, title: str) -> int:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO Course (lms_url_id, course_code, title)
            VALUES (?, ?, ?)
            ON CONFLICT(lms_url_id) DO UPDATE
              SET course_code = excluded.course_code,
                  title       = excluded.title
            """,
            (lms_url_id, course_code, title),
        )
        row = conn.execute(
            "SELECT course_id FROM Course WHERE lms_url_id = ?", (lms_url_id,)
        ).fetchone()
    return row["course_id"]


def upsert_enrollment(user_id: int, course_id: int, role: str = "student"):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO Enrollment (user_id, course_id, role)
            VALUES (?, ?, ?)
            """,
            (user_id, course_id, role),
        )


# ── Material ──────────────────────────────────────────

def upsert_material(
    course_id: int, title: str, file_type: str, file_path: str, checksum: str
) -> int | None:
    with get_conn() as conn:
        # 동일 체크섬이면 스킵
        exists = conn.execute(
            "SELECT material_id FROM Material WHERE checksum = ?", (checksum,)
        ).fetchone()
        if exists:
            return exists["material_id"]

        cur = conn.execute(
            """
            INSERT INTO Material (course_id, title, file_type, file_path, checksum)
            VALUES (?, ?, ?, ?, ?)
            """,
            (course_id, title, file_type, file_path, checksum),
        )
    return cur.lastrowid


# ── Personal_Log ─────────────────────────────────────

def insert_personal_log(user_id: int, course_id: int, material_id: int | None, stay_time: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO Personal_Log (user_id, course_id, material_id, stay_time) VALUES (?,?,?,?)",
            (user_id, course_id, material_id, stay_time),
        )


# ── Learning Activity ─────────────────────────────────

def clear_activities(user_id: int, course_id: int):
    """동기화 전 해당 과목 활동 전체 삭제 — 제출 완료된 항목도 자동 정리됨."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM Learning_Activity WHERE user_id=? AND course_id=?",
            (user_id, course_id),
        )


def upsert_activity(
    user_id: int, course_id: int, title: str, status: str, due_date
):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO Learning_Activity (user_id, course_id, title, status, due_date) VALUES (?,?,?,?,?)",
            (user_id, course_id, title, status, due_date),
        )


# ── Doc_Chunk ─────────────────────────────────────────

def insert_doc_chunks(material_id: int, chunks: list[dict]):
    """chunks: [{content, page_ref, chunk_index}]"""
    with get_conn() as conn:
        for c in chunks:
            cur = conn.execute(
                """
                INSERT INTO Doc_Chunk (material_id, content, page_ref, chunk_index)
                VALUES (?, ?, ?, ?)
                """,
                (material_id, c["content"], c["page_ref"], c["chunk_index"]),
            )
            conn.execute(
                "INSERT INTO Doc_Chunk_fts(rowid, content) VALUES (?, ?)",
                (cur.lastrowid, c["content"]),
            )


def chunks_exist(material_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM Doc_Chunk WHERE material_id = ? LIMIT 1", (material_id,)
        ).fetchone()
    return row is not None


def search_chunks(course_id: int | None, keywords: str, limit: int = 8) -> list[dict]:
    """FTS5 키워드 검색 — chunk_id · material_id · page_ref · snippet 반환."""
    with get_conn() as conn:
        if course_id:
            rows = conn.execute(
                """
                SELECT dc.chunk_id, dc.material_id, dc.page_ref, dc.content AS snippet
                FROM Doc_Chunk_fts
                JOIN Doc_Chunk dc ON dc.chunk_id = Doc_Chunk_fts.rowid
                JOIN Material  m  ON m.material_id = dc.material_id
                WHERE m.course_id = ? AND Doc_Chunk_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (course_id, keywords, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT dc.chunk_id, dc.material_id, dc.page_ref, dc.content AS snippet
                FROM Doc_Chunk_fts
                JOIN Doc_Chunk dc ON dc.chunk_id = Doc_Chunk_fts.rowid
                WHERE Doc_Chunk_fts MATCH ?
                ORDER BY rank LIMIT ?
                """,
                (keywords, limit),
            ).fetchall()
    return [dict(r) for r in rows]


# ── Chat ──────────────────────────────────────────────

def create_chat_session(user_id: int, course_id: int = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO Chat_Session (user_id, course_id) VALUES (?, ?)",
            (user_id, course_id),
        )
    return cur.lastrowid


def insert_chat_log(
    session_id: int, role: str, content: str,
    keywords: str = None, sources: str = None
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO Chat_Log (session_id, role, content, keywords, sources)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, keywords, sources),
        )
        conn.execute(
            "INSERT INTO Chat_Log_fts(rowid, content, keywords) VALUES (?, ?, ?)",
            (cur.lastrowid, content, keywords or ""),
        )
    return cur.lastrowid


def search_chat_logs(session_id: int, keywords: str, limit: int = 20) -> list[dict]:
    """Chat_Log FTS5 검색 — 이전 대화 이력에서 키워드 매칭."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT cl.chat_id, cl.role, cl.content, cl.keywords,
                   cl.sources, cl.feedback_score, cl.created_at
            FROM Chat_Log_fts
            JOIN Chat_Log cl ON cl.chat_id = Chat_Log_fts.rowid
            WHERE cl.session_id = ? AND Chat_Log_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (session_id, keywords, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_chat_history(session_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT chat_id, role, content, sources, created_at
            FROM Chat_Log WHERE session_id = ? ORDER BY created_at
            """,
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]
