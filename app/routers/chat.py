import os
import re
import json
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

router = APIRouter()


def extract_keywords(text: str) -> str:
    return re.sub(r'[^\w\s]', ' ', text).strip()


def get_course_title(course_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT title FROM Course WHERE course_id = ?",
            (course_id,)
        ).fetchone()
    return row["title"] if row else "Unknown Course"


def build_prompt(query, chunks, history, course_title):
    system = (
        f"You are a course tutor for '{course_title}'. "
        f"Answer based only on the provided lecture materials. "
        f"Always cite the source page number in your answer."
    )
    context_block = "\n\n".join(
        f"[Source {i+1} | page {c['page_ref']}]\n{c['snippet']}"
        for i, c in enumerate(chunks)
    )
    history_block = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}"
        for m in history[-6:]
    )
    if context_block and history_block:
        user_prompt = f"{context_block}\n\n---\n{history_block}\nUser: {query}"
    elif context_block:
        user_prompt = f"{context_block}\n\n---\nUser: {query}"
    else:
        user_prompt = f"User: {query}"
    return system, user_prompt


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    session_id = create_chat_session(req.user_id, req.course_id)
    history = get_chat_history(session_id)
    keywords = extract_keywords(req.question)

    chunks = []
    if req.course_id:
        chunks = search_chunks(
            course_id=req.course_id,
            keywords=keywords,
            limit=8
        )

    course_title = get_course_title(req.course_id) if req.course_id else "your course"
    system, user_prompt = build_prompt(req.question, chunks, history, course_title)

    try:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        answer_text = response.content[0].text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude API error: {e}")

    sources_list = [
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
