# PPT Content — LMS AI Copilot
> 슬라이드에 실제로 들어갈 텍스트만. 설명 없음.

---

## Slide 1 — Title

**LMS-Aware AI Copilot**
*for Personalized Learning*

HUFS · ISD Team · 2026

`Chrome Extension MV3` `FastAPI` `SQLite FTS5` `Groq llama-3.3-70b` `SSE Streaming`

---

## Slide 2 — ERD

**Data Model — 9 tables + 2 FTS5 indexes**

| Table | Key Fields |
|---|---|
| User | lms_id, enc_session_cookie, last_sync_at |
| Course / Enrollment | lms_url_id (KJKEY), role |
| Material | title, file_type, checksum |
| Doc_Chunk | content, page_ref, chunk_index |
| Learning_Activity | title, status, due_date |
| Personal_Log | stay_time (체류 시간) |
| Chat_Session | user_id, course_id |
| Chat_Log | role, content, keywords, sources, feedback_score |

`Doc_Chunk_fts` `Chat_Log_fts` — FTS5 virtual tables

---

## Slide 3 — System Architecture

**Chrome Extension**
- JSESSIONID 자동 포착 (Cookie Interceptor)
- Sidebar UI · Personal_Log stay-time 측정

**FastAPI Backend**
- `POST /sync` · `/sync/delta` · `/chat` · `/chat/stream` · `/feedback` · `/log`

**e-Class Scraper**
- Cookie injection → AJAX 직접 호출
- `report_list.acl` · `project_list.acl` POST · `test_list_form.acl` GET

**Ingest Pipeline**
- PDF / PPTX → 페이지 단위 청크 → FTS5 인덱싱
- MD5 체크섬 중복 방지

**RAG Engine**
- Smart Router: ACTIVITY_KW → Learning_Activity / MATERIAL_KW → FTS5
- Keyword 추출: llama-3.1-8b (토큰 절약)
- 답변: llama-3.3-70b → 429 시 8b fallback
- D-day 계산: Python에서 직접 계산 후 프롬프트 주입

---

## Slide 4 — Sequence Diagrams

**① Sync Flow**

```
User → Extension: 동기화 클릭
Extension → API: POST /sync {cookie}
API → Scraper → e-Class: JSESSIONID 주입
Scraper → DB: upsert user / course / enrollment
Scraper → e-Class: AJAX POST report_list, project_list
Scraper → DB: clear_activities → upsert_activity
Scraper → DB: PDF chunk → FTS5 insert
API → Extension: 완료
```

**② RAG Chat Flow (SSE Streaming)**

```
User → Extension: 질문
Extension → API: POST /chat/stream {session_id}
API: Smart Router 분기
  ├─ 과제 질문 → DB Learning_Activity (D-day 계산)
  └─ 자료 질문 → extract_keywords(8b) → FTS5 MATCH
API → Groq: llama-3.3-70b, stream=True
Groq → API → Extension: SSE delta chunks (실시간)
API → DB: INSERT Chat_Log (keywords, sources)
Extension → User: 실시간 렌더링 + 출처 태그 + 피드백
```

---

## Slide 5 — Demo

**Live Demo**

| # | Action | What to show |
|---|---|---|
| ① | 동기화 | 버튼 클릭 → "방금 동기화" |
| ② | 과목 감지 | 강의실 입장 → 헤더 과목명 자동 표시 |
| ③ | 과제 질문 | "이번 주 과제 마감일이 언제야?" → D-day 스트리밍 |
| ④ | 강의 질문 | "Merge Sort 시간복잡도 설명해줘" → 출처 페이지 태그 |
| ⑤ | 연속 대화 | "그럼 Quick Sort랑 비교하면?" → 세션 유지 |
| ⑥ | 피드백 | 👍 클릭 → feedback_score DB 저장 |
