from fastapi import APIRouter
from pydantic import BaseModel
from db.db import insert_personal_log, get_conn

router = APIRouter()


class LogRequest(BaseModel):
    user_id: int
    course_id: int
    material_id: int | None = None
    stay_time: int  # seconds


@router.post("")
def log_view(req: LogRequest):
    insert_personal_log(req.user_id, req.course_id, req.material_id, req.stay_time)
    return {"status": "ok"}


@router.get("")
def get_logs(user_id: int, course_id: int | None = None):
    with get_conn() as conn:
        if course_id:
            rows = conn.execute(
                """SELECT pl.log_id, pl.material_id, m.title, pl.stay_time, pl.course_id
                   FROM Personal_Log pl
                   LEFT JOIN Material m ON m.material_id = pl.material_id
                   WHERE pl.user_id = ? AND pl.course_id = ?
                   ORDER BY pl.log_id DESC LIMIT 50""",
                (user_id, course_id)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT pl.log_id, pl.material_id, m.title, pl.stay_time, pl.course_id
                   FROM Personal_Log pl
                   LEFT JOIN Material m ON m.material_id = pl.material_id
                   WHERE pl.user_id = ?
                   ORDER BY pl.log_id DESC LIMIT 50""",
                (user_id,)
            ).fetchall()
    return [dict(r) for r in rows]
