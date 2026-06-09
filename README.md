# LMS-Aware AI Copilot for Personalized Learning

HUFS e-Class와 연동하는 Chrome Extension + FastAPI RAG 파이프라인.

## Quick Start

```bash
pip install -r requirements.txt
echo "GROQ_API_KEY=your_key" > .env
python -c "from db.db import init_schema; init_schema()"
python -m uvicorn app.main:app --port 8001
```

Chrome: `chrome://extensions` → Load unpacked → `extension/` 폴더 선택 → eclass.hufs.ac.kr 접속

## File Structure

```
├── app/
│   ├── main.py                  # FastAPI 앱, CORS 설정
│   ├── routers/
│   │   ├── chat.py              # POST /chat, /chat/stream (SSE), smart router
│   │   ├── sync.py              # POST /sync, /sync/delta
│   │   ├── courses.py           # GET /courses
│   │   └── log.py               # POST /log (Personal_Log)
│   └── schemas/
│       ├── chat.py
│       └── sync.py
│
├── db/
│   ├── schema.sql               # DDL — 9 tables + 2 FTS5 virtual tables
│   ├── db.py                    # DB helpers, get_hybrid_history
│   ├── init_db.py
│   └── seed.py
│
├── pipeline/
│   ├── sync.py                  # run_sync(), run_sync_delta()
│   └── chunker.py               # PDF/PPTX → Doc_Chunk + FTS5
│
├── scraper/
│   └── eclass_scraper.py        # Cookie injection, AJAX endpoints
│
├── extension/
│   ├── manifest.json            # Chrome MV3
│   ├── background.js            # Service worker — sync, courses, feedback
│   ├── content.js               # Sidebar inject, Personal_Log stay-time
│   ├── panel.html / panel.js    # Sidebar UI, SSE streaming
│   ├── panel.css
│   └── icons/
│
├── data/
│   └── materials/               # 다운로드된 강의 PDF/PPTX (KJKEY별 폴더)
│
├── docs/
│   ├── diagrams/
│   │   ├── erd3.html            # ERD (mermaid)
│   │   ├── architecture.html    # 시스템 아키텍처 (3 tabs)
│   │   ├── sequence.html        # 시퀀스 다이어그램 (2 tabs)
│   │   └── mermaid.min.js
│   ├── Final_Report.md
│   ├── Presentation_Script.md
│   └── PPT_Content.md
│
├── lms_copilot.db               # SQLite (DB_PATH env로 override 가능)
├── requirements.txt
├── .env                         # GROQ_API_KEY
└── .env.example
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| POST | /sync | 전체 동기화 |
| POST | /sync/delta | 알림 기반 증분 동기화 |
| POST | /chat | JSON 응답 |
| POST | /chat/stream | SSE 스트리밍 응답 |
| GET  | /chat/{session_id} | 대화 이력 |
| POST | /chat/{id}/feedback | 👍/👎 피드백 |
| GET  | /courses | 수강 과목 목록 |
| POST | /log | Personal_Log 체류 시간 기록 |
| GET  | /health | 서버 상태 확인 |

## Tech Stack

| 구분 | 기술 |
|---|---|
| Extension | Chrome MV3, Vanilla JS |
| Backend | Python 3.12, FastAPI, Uvicorn |
| Database | SQLite 3 + FTS5 (unicode61) |
| LLM | Groq — llama-3.3-70b / llama-3.1-8b |
| Scraping | requests, BeautifulSoup4 |
| PDF/PPTX | pdfplumber, python-pptx |
