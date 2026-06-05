from fastapi import APIRouter
from db.db import get_conn

router = APIRouter()


@router.get("")
def get_courses(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.course_id, c.lms_url_id, c.course_code, c.title
            FROM Course c
            JOIN Enrollment e ON e.course_id = c.course_id
            WHERE e.user_id = ?
            """,
            (user_id,)
        ).fetchall()
    return {r["lms_url_id"]: {"course_id": r["course_id"], "title": r["title"]} for r in rows}
