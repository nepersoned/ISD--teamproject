# Presentation Script — LMS AI Copilot
**5 minutes · English · ISD Team · June 10, 2026**

---

## INTRO — No slide (20s)

> "Hi everyone. We built an **LMS-Aware AI Copilot** — a Chrome Extension that plugs directly into HUFS e-Class and answers questions about your lectures and assignments using a local AI pipeline.
>
> The problem is simple: students have to manually dig through e-Class every time they want to check a deadline or find what was covered in a lecture. We automated all of that.
>
> I'll walk you through the data model, system architecture, sequence flows, and then a live demo."

---

## SLIDE 1 — `erd3.html` (40s)

*[Open erd3.html — ERD diagram]*

> "Let's start with the data model.
>
> At the center you have **Doc_Chunk** — every PDF and PPTX from e-Class gets split into page-level chunks and indexed by two FTS5 virtual tables for Korean keyword search.
>
> **Learning_Activity** stores assignments, team projects, and quizzes. The key field here is `description` — we scrape the full assignment detail page separately, so when you ask 'what does this assignment require?', the system returns the professor's actual instructions, not just the title.
>
> **Chat_Log** tracks every conversation with the `keywords` used, the `sources` referenced as JSON, and a `feedback_score` — so the system can improve over time.
>
> Everything lives in a local SQLite database. Zero student data goes to any external server."

---

## SLIDE 2 — `architecture.html` Tab ① System Overview (30s)

*[Open architecture.html — Tab ① System Overview]*

> "Six layers. The Chrome Extension captures the JSESSIONID cookie automatically — no manual login. It also parses the course ID from the URL to show the course name in the sidebar.
>
> The FastAPI backend exposes nine endpoints. The key ones are `/sync`, `/sync/delta` for incremental sync, and `/chat/stream` which we'll see in the demo.
>
> The RAG Engine's Smart Router decides the path: assignment keywords go straight to Learning_Activity — no LLM involved. Lecture keywords go through keyword extraction, FTS5 search, and prompt assembly."

---

## SLIDE 3 — `architecture.html` Tab ② Ingest Pipeline (20s)

*[Click Tab ② Ingest Pipeline]*

> "When a file is downloaded, it goes through the ingest pipeline — text extracted page by page, MD5 checksum deduplication so we never re-process the same file, and FTS5 indexing with the unicode61 tokenizer for Korean support.
>
> Course announcements follow the same pipeline as a special `notice` type Material — same FTS5, same search."

---

## SLIDE 4 — `architecture.html` Tab ③ Chat / RAG Flow (20s)

*[Click Tab ③ Chat / RAG Flow]*

> "For a lecture question: the 8B model extracts keywords, FTS5 runs AND search first — if nothing matches, it retries with OR, then falls back to the raw question words excluding notice chunks.
>
> For an assignment question: we skip the LLM entirely. D-day tags are computed in Python and injected into the prompt — so the AI cannot get the date wrong."

---

## SLIDE 5 — `sequence.html` Tab ① LMS Sync (20s)

*[Open sequence.html — Tab ① LMS Sync]*

> "The sync flow. User clicks sync, the extension sends the cookie to `/sync`. The scraper authenticates via cookie injection and loops over every enrolled course — downloads materials, calls the AJAX endpoints directly for assignments and projects, scrapes each assignment's detail page, and writes everything to SQLite.
>
> `clear_activities` runs before insert — so completed assignments disappear automatically on the next sync."

---

## SLIDE 6 — `sequence.html` Tab ② RAG Q&A (20s)

*[Click Tab ② RAG Q&A]*

> "The chat flow. Question comes in, Smart Router checks for activity keywords. If it's a deadline question, we query Learning_Activity directly. If it's a lecture question, we extract keywords with the 8B model, search FTS5, build the prompt, and stream the answer back token by token via SSE.
>
> Every turn gets stored in Chat_Log with its keywords and source chunk references."

---

## DEMO — Browser (90s)

*[Switch to browser — Extension sidebar open, Machine Learning course page]*

> "Live demo. I'll show a 3-turn chain.
>
> *(click Sync)* First, sync. The extension grabs the session cookie automatically and sends it to our API — scrapes all enrolled courses, materials, assignments, notices. No login needed.
>
> *(navigate to ML course page)* The extension parses the course ID from the URL and shows the course name up here automatically.
>
> *(type: 머신러닝 과제 목록 알려줘)* Let me ask for the assignment list first.
>
> *(while streaming)* D-day tags — 'due today', 'overdue by 14 days'. Computed server-side in Python. Project #3 DNN is due today.
>
> *(type: DNN 과제 내용이 구체적으로 뭐야?)* Now let's ask what this DNN assignment actually requires.
>
> *(answer appears)* This comes directly from the assignment detail page — scraped separately, stored in the `description` field. Two experiment directions: changing network structure, tuning hyperparameters. This is not hallucinated — it's the professor's actual instructions.
>
> *(type: 그거 관련 강의자료 찾아줘)* Now I'm using a pronoun — 'that thing'. No explicit topic.
>
> *(answer appears)* The system resolves it to DNN from the previous conversation, searches the lecture PDFs, and returns source page numbers — pages 7, 11, 15. Grounded in the actual lecture material.
>
> *(click thumbs up)* Feedback stored as `feedback_score` in the database."

---

## WRAP-UP (20s)

> "To summarize — automatic cookie-based sync, assignment descriptions scraped from detail pages, smart routing that bypasses the LLM for deadline questions, D-day computed in Python, and a 3-turn pronoun-resolving chain — all running locally on SQLite.
>
> Thank you."

---

## Timing Guide

| Section | File | Time |
|---|---|---|
| Intro | — | 20s |
| ERD | `erd3.html` | 40s |
| Architecture Overview | `architecture.html` Tab ① | 30s |
| Ingest Pipeline | `architecture.html` Tab ② | 20s |
| Chat / RAG Flow | `architecture.html` Tab ③ | 20s |
| Sync Sequence | `sequence.html` Tab ① | 20s |
| RAG Q&A Sequence | `sequence.html` Tab ② | 20s |
| **Demo** | Browser | **90s** |
| Wrap-up | — | 20s |
| **Total** | | **~4:40** |

---

## Pre-Demo Checklist

- [ ] Server running: `C:\Users\kevin\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn app.main:app --port 8001`
- [ ] Chrome Extension loaded and enabled
- [ ] e-Class logged in — session cookie fresh
- [ ] Tabs pre-opened: `erd3.html`, `architecture.html`, `sequence.html`, ML course page
- [ ] Demo queries ready (copy-paste):
  - `머신러닝 과제 목록 알려줘`
  - `DNN 과제 내용이 구체적으로 뭐야?`
  - `그거 관련 강의자료 찾아줘`
