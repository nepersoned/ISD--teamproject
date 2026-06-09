# Backend Handover — RAG / Chat Engine

## Current State (at handover)

### Completed
| Item | Details |
|------|---------|
| Scraper | e-Class cookie injection, collects Courses · Materials · Learning_Activities |
| Delta Sync | Notification-triggered incremental sync (`/ilos/mp/notification_list.acl`) |
| Database | SQLite `lms_copilot.db` — 8 tables + `Doc_Chunk_fts` (FTS5 full-text index) |
| Chunker | PDF/PPTX → page-level Doc_Chunk rows, FTS5 indexed |
| FastAPI | `POST /sync`, `POST /sync/delta` working |

### DB State (local)
```
User              1 row
Course            7 rows
Enrollment        7 rows
Material         79 rows
Doc_Chunk        populated by chunker
Learning_Activity 20 rows
Chat_Session      0 rows  ← yours to fill
Chat_Log          0 rows  ← yours to fill
```

---

## Your Task: `/chat` RAG Engine

### Endpoints to implement
```
POST /chat
GET  /chat/{session_id}
POST /chat/{chat_id}/feedback
```

### Flow
```
1. Look up or create Chat_Session (user_id + course_id)
2. Load recent Chat_Log history (last N turns)
3. Extract keywords from query (strip stopwords or just split)
4. Search Doc_Chunk_fts via FTS5 → top-k chunks
5. Build prompt  (system + retrieved context + history + query)
6. Call Claude API
7. INSERT Chat_Log for user message
8. INSERT Chat_Log for assistant response (with sources JSON)
9. Return response + sources
```

### DB helpers (already implemented in `db/db.py`)
```python
from db.db import (
    create_chat_session,   # (user_id, course_id) -> session_id: int
    insert_chat_log,       # (session_id, role, content, keywords, sources) -> chat_id: int
    get_chat_history,      # (session_id) -> list[{role, content, ...}]
    search_chunks,         # (course_id, keywords, limit) -> list[{chunk_id, material_id, page_ref, snippet}]
    search_chat_logs,      # (session_id, keywords, limit) -> list[{chat_id, role, content, ...}]
)
```

### `search_chunks` usage
```python
results = search_chunks(course_id=3, keywords="neural network gradient", limit=8)
# returns:
# [
#   {"chunk_id": 42, "material_id": 7, "page_ref": 5, "snippet": "...highlighted..."},
#   ...
# ]
```
FTS5 `MATCH` syntax: space-separated terms = AND search. Quote phrases for exact match.  
**Strip special characters from user input before passing as keywords:**
```python
import re
keywords = re.sub(r'[^\w\s]', ' ', query).strip()
```

### `keywords` field — **required for chat history search**
Extract keywords from the user's query and store them in `Chat_Log.keywords`.
This enables `search_chat_logs()` to find past conversations by topic.

```python
import re
keywords = re.sub(r'[^\w\s]', ' ', query).strip()   # strip special chars
# pass to insert_chat_log(..., keywords=keywords, ...)
```
Store the **same keywords string** for both the user message and assistant response rows.

### `sources` JSON format (store in `Chat_Log.sources`)
```json
[
  {"chunk_id": 42, "material_id": 7, "page_ref": 5},
  {"chunk_id": 43, "material_id": 7, "page_ref": 6}
]
```
```python
import json
sources_str = json.dumps(sources_list)   # pass to insert_chat_log
```

### Claude API
```python
import anthropic

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": prompt}]
)
answer = response.content[0].text
```
Set `ANTHROPIC_API_KEY` in `.env`.

### Suggested prompt structure
```python
system = f"You are a course tutor for '{course_title}'. Answer based only on the provided lecture materials."

context_block = "\n\n".join(
    f"[Source {i+1} | page {c['page_ref']}]\n{c['snippet']}"
    for i, c in enumerate(chunks)
)

history_block = "\n".join(
    f"{m['role'].capitalize()}: {m['content']}"
    for m in history[-6:]   # last 3 turns
)

prompt = f"{context_block}\n\n---\n{history_block}\nUser: {query}"
```

---

## Schema Reference
```sql
Chat_Session : session_id · user_id · course_id · created_at
Chat_Log     : chat_id · session_id · role · content
             · keywords TEXT · sources TEXT (JSON) · feedback_score · created_at
Doc_Chunk    : chunk_id · material_id · content · page_ref · chunk_index
Material     : material_id · course_id · title · file_type · file_path · checksum
Course       : course_id · lms_url_id · course_code · title
```

---

## File Structure
```
app/
  routers/
    sync.py    ← done
    chat.py    ← implement here
  schemas/
    sync.py    ← done
    chat.py    ← implement here
db/
  db.py        ← search_chunks, insert_chat_log, etc. already here
  schema.sql   ← complete with FTS5
pipeline/
  sync.py      ← run_sync / run_sync_delta
  chunker.py   ← chunk_material / run_chunker
scraper/
  eclass_scraper.py
```

---

## Local Setup
```bash
# Install dependencies
pip install fastapi uvicorn requests beautifulsoup4 lxml python-dotenv pymupdf python-pptx anthropic

# .env file (create manually — never commit)
ECLASS_ID=202501718
ECLASS_COOKIE=JSESSIONID=<copy from browser DevTools>
ANTHROPIC_API_KEY=sk-ant-...
DB_PATH=lms_copilot.db

# Init DB + run chunker (populates Doc_Chunk)
python -m db.init_db
python -m pipeline.chunker

# Start server
uvicorn app.main:app --reload
```

---

## Important Notes
- **Never commit `.env`** — it is gitignored
- `lms_copilot.db` is also gitignored — each developer runs sync locally
- Get a fresh `JSESSIONID`: log into e-Class in Chrome → F12 → Application → Cookies → copy value
- FTS5 search is **case-insensitive** by default with `tokenize='unicode61'`
- The `feedback` endpoint just updates `Chat_Log.feedback_score` (1 = thumbs up, -1 = thumbs down)
