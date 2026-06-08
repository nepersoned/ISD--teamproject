from pydantic import BaseModel
from typing import Any


class ChatRequest(BaseModel):
    user_id: int
    course_id: int | None = None
    question: str
    session_id: int | None = None


class ChatResponse(BaseModel):
    session_id: int
    chat_id: int
    answer: str
    sources: list[Any] = []
