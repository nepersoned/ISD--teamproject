from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import sync, chat, courses

app = FastAPI(title="LMS AI Copilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Chrome Extension origin
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sync.router, prefix="/sync", tags=["sync"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(courses.router, prefix="/courses", tags=["courses"])


@app.get("/health")
def health():
    return {"status": "ok"}
