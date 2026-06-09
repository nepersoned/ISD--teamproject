# LMS-Aware AI Copilot — 시스템 설명서

> HUFS e-Class 데이터를 기반으로 개인화된 학습 보조 AI를 제공하는 프로젝트

---

## 시스템 아키텍처 설명

시스템은 크게 **6개 레이어**로 구성됩니다.

### ① Chrome Extension (프론트엔드)
사용자가 e-Class 웹 페이지를 열면 브라우저 오른쪽에 AI 사이드바가 오버레이 형태로 표시됩니다.  
별도 페이지 이동 없이 강의 페이지 위에서 바로 질문하고 답변을 받을 수 있습니다.  
로그인 세션 쿠키를 캡처해 백엔드에 전달하는 역할도 담당합니다.

### ② FastAPI 백엔드
두 가지 핵심 엔드포인트를 제공합니다.
- `POST /sync` — e-Class 스크래핑 및 DB 저장을 트리거
- `POST /chat` — 사용자 질문을 받아 RAG 파이프라인을 거쳐 AI 답변 반환

### ③ HUFS e-Class (외부 LMS)
스크래핑 대상 시스템입니다.  
세션 쿠키 기반으로 로그인 상태를 유지한 채 강의자료(PDF, PPT), 과제, 퀴즈 정보를 수집합니다.

### ④ RAG 엔진 (Phase 2)
수집한 강의자료를 일정 크기의 청크로 분할하고 임베딩 벡터로 변환합니다.  
사용자가 질문하면 질문 벡터와 cosine 유사도를 계산해 가장 관련성 높은 강의자료 조각을 검색합니다.  
검색 결과 + 대화 이력을 Claude API에 전달해 최종 답변을 생성합니다.

### ⑤ PostgreSQL + pgvector
ERD에 정의된 9개 테이블로 구성된 중앙 데이터베이스입니다.  
`Doc_Chunk` 테이블에 pgvector 확장을 적용해 1536차원 임베딩 벡터를 저장하고 IVFFlat 인덱스로 빠른 유사도 검색을 지원합니다.

### ⑥ 파일 스토리지
다운로드된 강의자료(PDF, PPT)가 `data/materials/{course_id}/` 경로에 저장됩니다.  
MD5 체크섬으로 중복 다운로드를 방지합니다.

---

## 시퀀스 다이어그램 설명

### Sequence 1 — LMS 동기화 흐름

사용자가 Chrome Extension에서 동기화 버튼을 누르면 다음 순서로 진행됩니다.

1. Extension이 FastAPI `POST /sync`를 호출합니다.
2. Sync Service가 e-Class 로그인 엔드포인트(`login.acl`)에 POST 요청을 보내 세션 쿠키를 획득합니다.
3. 획득한 쿠키로 수강 과목 목록 페이지를 스크래핑합니다.
4. 각 과목마다 강의자료 목록 페이지를 요청하여 파일을 다운로드하고, MD5 체크섬과 함께 `Material` 테이블에 저장합니다.
5. 과제·퀴즈 목록도 수집하여 `Learning_Activity` 테이블에 저장합니다.
6. 모든 과목 처리 후 `User.last_sync_at`을 현재 시각으로 갱신합니다.

루프 구조로 인해 과목 수·파일 수에 비례하여 실행 시간이 증가하며, 향후 비동기(asyncio) 처리로 개선 예정입니다.

---

### Sequence 2 — RAG Q&A 흐름

사용자가 사이드바에 질문을 입력하면 다음 순서로 진행됩니다.

1. Extension이 FastAPI `POST /chat`을 호출합니다.
2. 현재 세션이 없으면 `Chat_Session`을 새로 생성하고, 사용자 메시지를 `Chat_Log`에 기록합니다.
3. RAG Pipeline이 질문 텍스트를 임베딩 벡터로 변환합니다.
4. pgvector에서 cosine 유사도 기준 Top-K 강의자료 청크를 검색합니다.
5. 최근 N턴의 대화 이력을 `Chat_Log`에서 조회합니다.
6. **시스템 프롬프트 + 대화 이력 + 검색된 청크 + 질문**을 합쳐 Claude API에 전달합니다.
7. 반환된 답변과 출처 정보를 `Chat_Log`에 저장하고 Extension에 전달합니다.

이 구조 덕분에 동일 강의를 듣는 학생이라도 자신의 학습 이력과 질문 맥락에 따라 개인화된 답변을 받을 수 있습니다.

---

## DB 스키마 요약

| 테이블 | 주요 컬럼 | 설명 |
|---|---|---|
| `User` | lms_id, enc_session_cookie | e-Class 계정 및 세션 정보 |
| `Course` | lms_url_id, course_code, title | 수강 과목 |
| `Enrollment` | user_id, course_id, role | 수강 관계 (학생/교수) |
| `Material` | file_type, file_path, checksum | 강의자료 파일 메타데이터 |
| `Doc_Chunk` | content, embedding (1536d) | 자료 분할 청크 + 임베딩 벡터 |
| `Learning_Activity` | title, status, due_date | 과제·퀴즈 현황 |
| `Personal_Log` | stay_time | 자료 열람 시간 기록 |
| `Chat_Session` | user_id, course_id | 채팅 세션 |
| `Chat_Log` | role, content, sources | 대화 내역 및 출처 |

---

## 기술 스택

| 레이어 | 기술 |
|---|---|
| 프론트엔드 | Chrome Extension (React, Phase 3) |
| 백엔드 | Python · FastAPI · Uvicorn |
| 스크래핑 | requests · BeautifulSoup4 (세션 기반) |
| 데이터베이스 | PostgreSQL · pgvector |
| AI | Claude API (claude-sonnet-4-6) |

---

## 개발 로드맵

- [x] **Phase 1** — e-Class 스크래퍼 + PostgreSQL DB 구축
- [x] **Phase 1** — FastAPI 백엔드 (`/sync`, `/chat` 라우터)
- [ ] **Phase 2** — PDF/PPT 청킹 + pgvector 임베딩 파이프라인
- [ ] **Phase 2** — RAG 엔진 (Claude API 연동)
- [ ] **Phase 3** — Chrome Extension UI (React 사이드바)
