# 프론트엔드 진행상황

> Chrome Extension 사이드바 구현 현황

---

## 완료된 작업

### Extension 기본 구조
- `manifest.json` — MV3, 권한 설정 (cookies, storage, host_permissions)
- `content.js` — e-Class 페이지에 사이드바 iframe 삽입, 토글 버튼, 과목 URL 자동 감지
- `background.js` — chrome.cookies API로 JSESSIONID 자동 읽기, 백엔드 API 호출
- `panel.html` / `panel.css` / `panel.js` — 사이드바 UI 및 동작 로직

### 구현된 기능

#### 사이드바 UI
- 오른쪽 화면에 iframe 형태로 오버레이
- 우측 중앙 AI 토글 버튼으로 열기/닫기
- 사이드바 열릴 때 페이지 콘텐츠 왼쪽으로 밀림 (marginRight 적용)
- 다크 헤더 + 현재 과목명 표시

#### 동기화
- 학번만 입력하면 JSESSIONID 자동 캡처하여 동기화
- 첫 동기화 전: "동기화" 버튼
- 동기화 중: "동기화 중..." 표시
- 동기화 완료 후: "n분 전 동기화" (1분마다 자동 갱신)

#### 채팅
- 메시지 전송 (Enter 또는 버튼)
- 답변에 출처 페이지 태그 표시
- 👍 / 👎 피드백 버튼
- **페이지 이동해도 대화 내용 유지** (`chrome.storage.local` 저장)
- 빈 화면에 힌트 질문 칩 3개 표시

### 백엔드 연동 수정
- `app/routers/chat.py` — PostgreSQL → SQLite 헬퍼 함수로 교체, OpenAI API 연동
- `db/db.py` — `search_chunks()` course_id 없을 때 전체 검색 지원
- Claude API → OpenAI API (`gpt-4o-mini`) 로 교체

---

## 남은 작업

- [ ] `GET /courses?user_id=X` API 백엔드 구현 후 과목 자동 매핑 연결 (`panel.js` TODO 주석 해제)
- [ ] 대화 내용 초기화 버튼
- [ ] 답변 텍스트 마크다운 렌더링
- [ ] 세션별 대화 분리 (과목마다 다른 대화 내역)

---

## 실행 방법

1. 백엔드 서버 실행
   ```bash
   uvicorn app.main:app --reload
   ```

2. PDF 청킹 (처음 한 번만)
   ```bash
   pip install pymupdf python-pptx openai
   python -m pipeline.chunker
   ```

3. Chrome Extension 로드
   - `chrome://extensions` → 개발자 모드 ON
   - "압축해제된 확장 프로그램 로드" → `extension/` 폴더 선택

4. e-Class 접속 → 학번 입력 → 동기화 → 질문
