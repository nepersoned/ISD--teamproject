import os
import re
import json
from datetime import date
from groq import Groq
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.schemas.chat import ChatRequest, ChatResponse
from db.db import (
    create_chat_session,
    insert_chat_log,
    get_chat_history,
    get_hybrid_history,
    search_chunks,
    get_conn,
)

ACTIVITY_KEYWORDS = {'과제', '퀴즈', '마감', '제출', '시험', '활동', '언제', '오늘', '이번주', '남은', '해야'}
MATERIAL_KEYWORDS = {'강의자료', '강의', '자료', '내용', '개념', '설명', '정리', '요약'}

router = APIRouter()

SMALL_MODEL = "llama-3.1-8b-instant"
LARGE_MODEL = "llama-3.3-70b-versatile"


def _get_client() -> Groq | None:
    key = os.getenv("GROQ_API_KEY")
    return Groq(api_key=key) if key else None


def _resolve_session(user_id: int, course_id: int | None, session_id: int | None) -> int:
    if session_id:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT session_id FROM Chat_Session WHERE session_id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
        if row:
            return row["session_id"]
    return create_chat_session(user_id, course_id)


def extract_keywords(client: Groq, question: str, history: list[dict] | None = None) -> str:
    try:
        context = ""
        if history:
            # user 메시지만 — assistant 응답의 페이지/출처 텍스트가 키워드를 오염시킴
            user_msgs = [m for m in history if m['role'] == 'user'][-3:]
            if user_msgs:
                context = "\n".join(f"user: {m['content'][:120]}" for m in user_msgs)
                context = f"[이전 질문]\n{context}\n\n"
        res = client.chat.completions.create(
            model=SMALL_MODEL,
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": (
                    f"{context}다음 질문에서 PDF 강의자료 검색에 쓸 핵심 영어/한국어 단어 2~3개만 "
                    "공백으로 구분해서 출력해. 대명사(그거, 이것 등)는 앞 대화 맥락에서 실제 주제어로 바꿔서 출력해. "
                    "다른 말 없이 단어만 출력:\n" + question
                )
            }]
        )
        raw = res.choices[0].message.content.strip()
        # 개행·특수문자 제거 후 단어만 추출, 최대 5개
        words = re.findall(r'[가-힣A-Za-z0-9]{2,}', raw)
        # 문장 조사/어미 제거 (내용에는, 포함됩니다 등 FTS에 무의미한 단어 제거)
        stopwords = {'내용에는', '포함됩니다', '다음과', '같은', '핵심', '단어가', '있습니다', '합니다', '이며', '으로'}
        words = [w for w in words if w not in stopwords]
        return ' '.join(words[:5]) if words else ''
    except Exception:
        return _safe_keywords(question)


def _safe_keywords(question: str) -> str:
    cleaned = re.sub(r'[^\w\s]', ' ', question).strip()
    return ' '.join(cleaned.split()[:4])


def get_course_title(course_id: int) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT title FROM Course WHERE course_id = ?", (course_id,)).fetchone()
    return row["title"] if row else "Unknown Course"


def get_activities(user_id: int, course_id: int = None) -> list[dict]:
    with get_conn() as conn:
        if course_id:
            rows = conn.execute(
                """SELECT c.title as course, la.title, la.status, la.due_date, la.description
                   FROM Learning_Activity la
                   JOIN Course c ON c.course_id = la.course_id
                   WHERE la.user_id = ? AND la.course_id = ?
                   GROUP BY la.title, la.due_date
                   ORDER BY la.due_date""",
                (user_id, course_id)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT c.title as course, la.title, la.status, la.due_date, la.description
                   FROM Learning_Activity la
                   JOIN Course c ON c.course_id = la.course_id
                   WHERE la.user_id = ?
                     AND (la.due_date IS NULL OR la.due_date >= date('now', '-14 days'))
                   GROUP BY la.title, la.due_date
                   ORDER BY la.due_date""",
                (user_id,)
            ).fetchall()
    return [dict(r) for r in rows]


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
                    if diff < 0:   tag = f"마감 {abs(diff)}일 지남"
                    elif diff == 0: tag = "오늘 마감"
                    elif diff == 1: tag = "내일 마감 (D-1)"
                    else:           tag = f"D-{diff}"
                except Exception:
                    tag = ""
                due_str = f"{raw_due} ({tag})"
            else:
                due_str = "마감일 없음"
            status = "확인 불가" if a['status'] == "unknown" else a['status']
            line = f"- [{a['course']}] {a['title']} | 마감: {due_str} | 상태: {status}"
            if a.get('description'):
                line += f"\n  내용: {a['description'][:400]}"
            lines.append(line)
        activity_block = "\n".join(lines)

    history_block = "\n".join(
        f"{m['role'].capitalize()}: {m['content']}"
        for m in history[-6:]
    )

    parts = []
    if context_block:   parts.append(context_block)
    if activity_block:  parts.append(activity_block)
    if history_block:   parts.append(history_block)
    parts.append(f"User: {query}")

    return system, "\n\n---\n".join(parts)


def _build_context(client: Groq, req: ChatRequest, session_id: int):
    """스마트 라우팅: 활동/자료 분기, 키워드 추출, 청크 검색."""
    history = get_hybrid_history(session_id, _safe_keywords(req.question))
    keywords = extract_keywords(client, req.question, history) or _safe_keywords(req.question)

    is_activity = any(kw in req.question for kw in ACTIVITY_KEYWORDS)
    needs_material = any(kw in req.question for kw in MATERIAL_KEYWORDS)
    activities, chunks = [], []

    if is_activity:
        activities = get_activities(req.user_id, req.course_id)

    if not is_activity or not activities or needs_material:
        if keywords:
            # 먼저 AND 검색, 없으면 OR로 재시도
            chunks = search_chunks(course_id=req.course_id, keywords=keywords, limit=8)
            if not chunks:
                or_kw = ' OR '.join(keywords.split())
                chunks = search_chunks(course_id=req.course_id, keywords=or_kw, limit=8)
        if not chunks:
            # 원문 질문 단어 OR fallback — notice 청크 제외
            words = [w for w in re.sub(r'[^\w\s]', ' ', req.question).split() if len(w) > 1]
            fallback_kw = ' OR '.join(words)
            if fallback_kw:
                chunks = search_chunks(course_id=req.course_id, keywords=fallback_kw, limit=8,
                                       exclude_notice=True)

    course_title = get_course_title(req.course_id) if req.course_id else "수강 과목"
    system, user_prompt = build_prompt(req.question, chunks, history, course_title, activities)

    sources_list = [] if activities else [
        {"chunk_id": c["chunk_id"], "material_id": c["material_id"], "page_ref": c["page_ref"]}
        for c in chunks
    ]
    return keywords, system, user_prompt, sources_list


# ── POST /chat  (JSON 응답) ────────────────────────────────────────────────
@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest):
    client = _get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not set")

    session_id = _resolve_session(req.user_id, req.course_id, req.session_id)
    keywords, system, user_prompt, sources_list = _build_context(client, req, session_id)
    sources_str = json.dumps(sources_list)

    for model in [LARGE_MODEL, SMALL_MODEL]:
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_prompt},
                ],
            )
            answer_text = response.choices[0].message.content
            break
        except Exception as e:
            if "429" in str(e) and model == LARGE_MODEL:
                continue
            raise HTTPException(status_code=500, detail=f"Groq API error: {e}")
    else:
        raise HTTPException(status_code=503, detail="Groq 일일 한도 초과. 잠시 후 다시 시도하세요.")

    insert_chat_log(session_id, "user", req.question, keywords, None)
    chat_id = insert_chat_log(session_id, "assistant", answer_text, keywords, sources_str)

    return ChatResponse(
        session_id=session_id,
        chat_id=chat_id,
        answer=answer_text,
        sources=sources_list,
    )


# ── POST /chat/stream  (SSE 스트리밍) ─────────────────────────────────────
@router.post("/stream")
def chat_stream(req: ChatRequest):
    client = _get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="GROQ_API_KEY not set")

    session_id = _resolve_session(req.user_id, req.course_id, req.session_id)
    keywords, system, user_prompt, sources_list = _build_context(client, req, session_id)
    sources_str = json.dumps(sources_list)

    insert_chat_log(session_id, "user", req.question, keywords, None)

    def generate():
        full = []
        for model in [LARGE_MODEL, SMALL_MODEL]:
            try:
                stream = client.chat.completions.create(
                    model=model,
                    max_tokens=1024,
                    stream=True,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user",   "content": user_prompt},
                    ],
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content or ""
                    if delta:
                        full.append(delta)
                        yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
                break
            except Exception as e:
                if "429" in str(e) and model == LARGE_MODEL:
                    continue
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                return

        full_text = "".join(full)
        chat_id = insert_chat_log(session_id, "assistant", full_text, keywords, sources_str)
        yield (
            f"data: {json.dumps({'done': True, 'session_id': session_id, 'chat_id': chat_id, 'sources': sources_list}, ensure_ascii=False)}\n\n"
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── GET /chat/{session_id} ─────────────────────────────────────────────────
@router.get("/{session_id}")
def get_history(session_id: int):
    return get_chat_history(session_id)


# ── POST /chat/{chat_id}/feedback ─────────────────────────────────────────
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
