import os
import re
import json
from datetime import date
import anthropic
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
                """SELECT la.title, la.status, la.due_date, c.title as course
                   FROM Learning_Activity la
                   JOIN Course c ON c.course_id = la.course_id
                   WHERE la.user_id = ? AND la.course_id = ?
                   ORDER BY la.due_date""",
                (user_id, course_id)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT la.title, la.status, la.due_date, c.title as course
                   FROM Learning_Activity la
                   JOIN Course c ON c.course_id = la.course_id
                   WHERE la.user_id = ?
                   ORDER BY la.due_date""",
                (user_id,)
            ).fetchall()
    return [dict(r) for r in rows]

router = APIRouter()


def extract_keywords(client: anthropic.Anthropic, question: str) -> str:
    try:
        res = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": (
                    "다음 질문에서 PDF 강의자료 검색에 쓸 핵심 영어/한국어 단어 2~3개만 "
                    "공백으로 구분해서 출력해. 다른 말 없이 단어만 출력:\n" + question
                )
            }]
        )
        keywords = res.content[0].text.strip()
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
    if chunks or activities:
        system = (
            f"당신은 '{course_title}' 강의 튜터입니다. "
            f"오늘 날짜는 {today}입니다. "
            f"제공된 자료를 바탕으로 한국어로 답변하세요. "
            f"강의자료 인용 시 출처 페이지 번호를 표시하세요."
        )
    else:
        system = (
            f"당신은 '{course_title}' 강의 튜터입니다. "
            f"오늘 날짜는 {today}입니다. "
            f"관련 자료를 찾지 못했습니다. 일반적인 지식을 바탕으로 한국어로 답변하세요."
        )

    context_block = "\n\n".join(
        f"[강의자료 {i+1} | {c['page_ref']}페이지]\n{c['snippet']}"
        for i, c in enumerate(chunks)
    )

    activity_block = ""
    if activities:
        lines = ["[과제/활동 목록]"]
        for a in activities:
            due = a['due_date'] or '마감일 없음'
            lines.append(f"- [{a['course']}] {a['title']} | 마감: {due} | 상태: {a['status']}")
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


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    session_id = create_chat_session(req.user_id, req.course_id)
    history = get_chat_history(session_id)
    keywords = extract_keywords(client, req.question)

    # 과제/마감 관련 질문이면 Learning_Activity 조회, 강의자료 검색 건너뜀
    is_activity_question = any(kw in req.question for kw in ACTIVITY_KEYWORDS)
    activities = []
    chunks = []

    if is_activity_question:
        activities = get_activities(req.user_id, req.course_id)

    if not is_activity_question or not activities:
        chunks = search_chunks(course_id=req.course_id, keywords=keywords, limit=8)
        if not chunks:
            words = re.sub(r'[^\w\s]', ' ', req.question).split()
            fallback_kw = ' OR '.join(w for w in words if len(w) > 1)
            if fallback_kw:
                chunks = search_chunks(course_id=req.course_id, keywords=fallback_kw, limit=8)

    course_title = get_course_title(req.course_id) if req.course_id else "수강 과목"
    system, user_prompt = build_prompt(req.question, chunks, history, course_title, activities)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        answer_text = response.content[0].text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {e}")

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
