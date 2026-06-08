import os
import re
import json
from datetime import date
from groq import Groq
from fastapi import APIRouter, HTTPException
from app.schemas.chat import ChatRequest, ChatResponse
from db.db import (
    create_chat_session,
    insert_chat_log,
    get_chat_history,
    search_chunks,
    get_conn,
)

ACTIVITY_KEYWORDS = {'과제', '퀴즈', '마감', '제출', '시험', '활동', '언제', '오늘', '이번주', '남은', '해야'}

def get_activities(user_id: int, course_id: int = None) -> list[dict]:
    with get_conn() as conn:
        if course_id:
            rows = conn.execute(
                """SELECT c.title as course, la.title, la.status, la.due_date
                   FROM Learning_Activity la
                   JOIN Course c ON c.course_id = la.course_id
                   WHERE la.user_id = ? AND la.course_id = ?
                   GROUP BY la.title, la.due_date
                   ORDER BY la.due_date""",
                (user_id, course_id)
            ).fetchall()
        else:
            # 과목 미선택 시: 마감일 기준 최근 2주 이전은 제외, 예정 항목 우선
            rows = conn.execute(
                """SELECT c.title as course, la.title, la.status, la.due_date
                   FROM Learning_Activity la
                   JOIN Course c ON c.course_id = la.course_id
                   WHERE la.user_id = ?
                     AND (la.due_date IS NULL OR la.due_date >= date('now', '-14 days'))
                   GROUP BY la.title, la.due_date
                   ORDER BY la.due_date""",
                (user_id,)
            ).fetchall()
    return [dict(r) for r in rows]

router = APIRouter()


SMALL_MODEL = "llama-3.1-8b-instant"   # 키워드 추출용 (토큰 절약)
LARGE_MODEL = "llama-3.3-70b-versatile" # 답변용


def extract_keywords(client: Groq, question: str) -> str:
    try:
        res = client.chat.completions.create(
            model=SMALL_MODEL,
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": (
                    "다음 질문에서 PDF 강의자료 검색에 쓸 핵심 영어/한국어 단어 2~3개만 "
                    "공백으로 구분해서 출력해. 다른 말 없이 단어만 출력:\n" + question
                )
            }]
        )
        keywords = res.choices[0].message.content.strip()
        return re.sub(r'[^\w\s]', ' ', keywords).strip()
    except Exception:
        cleaned = re.sub(r'[^\w\s]', ' ', question).strip()
        return ' '.join(cleaned.split()[:4])


def get_course_title(course_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title FROM Course WHERE course_id = ?",
            (course_id,)
        ).fetchone()
    return row["title"] if row else "Unknown Course"


def build_prompt(query, chunks, history, course_title, activities=None):
    today = date.today().isoformat()
    system = (
        f"당신은 강의 튜터입니다. 오늘 날짜는 {today}입니다. "
        f"반드시 아래에 제공된 강의자료와 과제/활동 정보만을 근거로 한국어로 답변하세요. "
        f"과제/활동 목록이 제공된 경우: 질문에 특정 날짜가 언급되면 해당 날짜의 항목만, "
        f"'이번 주'이면 {today} 기준 7일 이내 마감 항목만, '전체'이면 전부 나열하세요. "
        f"상태가 'unknown'이면 '확인 불가'로 표시하세요. "
        f"제공된 자료에 없는 내용은 '해당 정보를 찾을 수 없습니다.'라고 답하세요. "
        f"외부 교재, 인터넷 자료, 일반 지식은 절대 언급하지 마세요. "
        f"강의자료 인용 시 출처 페이지 번호를 표시하세요."
    )

    context_block = "\n\n".join(
        f"[강의자료 {i+1} | {c['page_ref']}페이지]\n{c['snippet']}"
        for i, c in enumerate(chunks)
    )

    activity_block = ""
    if activities:
        from datetime import date as _date
        _today = _date.today()
        lines = ["[과제/활동 목록 — 오늘: " + today + "]"]
        for a in activities:
            raw_due = a['due_date']
            if raw_due:
                try:
                    d = _date.fromisoformat(raw_due)
                    diff = (d - _today).days
                    if diff < 0:
                        tag = f"마감 {abs(diff)}일 지남"
                    elif diff == 0:
                        tag = "오늘 마감"
                    elif diff == 1:
                        tag = "내일 마감 (D-1)"
                    else:
                        tag = f"D-{diff}"
                except Exception:
                    tag = ""
                due_str = f"{raw_due} ({tag})"
            else:
                due_str = "마감일 없음"
            status = "확인 불가" if a['status'] == "unknown" else a['status']
            lines.append(f"- [{a['course']}] {a['title']} | 마감: {due_str} | 상태: {status}")
        activity_block = "\n".join(lines)

    history_block = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}"
        for m in history[-6:]
    )

    parts = []
    if context_block: parts.append(context_block)
    if activity_block: parts.append(activity_block)
    if history_block:  parts.append(history_block)
    parts.append(f"User: {query}")

    return system, "\n\n---\n".join(parts)


def _safe_keywords(question: str) -> str:
    cleaned = re.sub(r'[^\w\s]', ' ', question).strip()
    return ' '.join(cleaned.split()[:4])


def _get_client() -> Groq | None:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return None
    return Groq(api_key=key)


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    client = _get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not set")

    session_id = create_chat_session(req.user_id, req.course_id)
    history = get_chat_history(session_id)
    keywords = extract_keywords(client, req.question) or _safe_keywords(req.question)

    # 과제/마감 관련 질문이면 Learning_Activity 조회, 강의자료 검색 건너뜀
    is_activity_question = any(kw in req.question for kw in ACTIVITY_KEYWORDS)
    activities = []
    chunks = []

    MATERIAL_KEYWORDS = {'강의자료', '강의', '자료', '내용', '개념', '설명', '정리', '요약'}
    needs_material = any(kw in req.question for kw in MATERIAL_KEYWORDS)

    if is_activity_question:
        activities = get_activities(req.user_id, req.course_id)

    # 순수 과제 질문이면 청크 검색 스킵, 강의자료 언급 있으면 같이 검색
    if not is_activity_question or not activities or needs_material:
        if keywords:
            chunks = search_chunks(course_id=req.course_id, keywords=keywords, limit=8)
        if not chunks:
            words = re.sub(r'[^\w\s]', ' ', req.question).split()
            fallback_kw = ' OR '.join(w for w in words if len(w) > 1)
            if fallback_kw:
                chunks = search_chunks(course_id=req.course_id, keywords=fallback_kw, limit=8)

    course_title = get_course_title(req.course_id) if req.course_id else "수강 과목"
    system, user_prompt = build_prompt(req.question, chunks, history, course_title, activities)

    for model in [LARGE_MODEL, SMALL_MODEL]:
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
            )
            answer_text = response.choices[0].message.content
            break
        except Exception as e:
            if "429" in str(e) and model == LARGE_MODEL:
                continue  # 70B 한도 초과 시 8B로 재시도
            raise HTTPException(status_code=500, detail=f"Groq API error: {e}")
    else:
        raise HTTPException(status_code=503, detail="Groq 일일 한도 초과. 잠시 후 다시 시도하세요.")

    # 과제 관련 답변이면 강의자료 출처 표시 안 함
    sources_list = [] if activities else [
        {"chunk_id": c["chunk_id"], "material_id": c["material_id"], "page_ref": c["page_ref"]}
        for c in chunks
    ]
    sources_str = json.dumps(sources_list)

    insert_chat_log(session_id, "user", req.question, keywords, None)
    chat_id = insert_chat_log(session_id, "assistant", answer_text, keywords, sources_str)

    return ChatResponse(
        session_id=session_id,
        chat_id=chat_id,
        answer=answer_text,
        sources=sources_list,
    )


@router.get("/{session_id}")
def get_history(session_id: int):
    return get_chat_history(session_id)


@router.post("/{chat_id}/feedback")
def feedback(chat_id: int, score: int):
    if score not in (1, -1):
        raise HTTPException(status_code=422, detail="score must be 1 or -1")
    with get_conn() as conn:
        conn.execute(
            "UPDATE Chat_Log SET feedback_score = ? WHERE chat_id = ?",
            (score, chat_id),
        )
    return {"status": "ok", "chat_id": chat_id, "score": score}
