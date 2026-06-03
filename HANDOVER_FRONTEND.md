# 프론트엔드 핸드오버 — Chrome Extension 사이드바

> 이 문서는 Chrome Extension 사이드바를 이어받는 팀원을 위한 가이드입니다.  
> 백엔드는 모두 완성되어 있으니, 프론트만 집중하면 됩니다.

---

## 전체 구조 한눈에 보기

```
사용자가 e-Class 페이지 열기
    ↓
Chrome Extension이 오른쪽에 사이드바 자동 표시
    ↓
학번 입력 → 동기화 버튼 클릭 (강의자료 DB에 저장됨)
    ↓
강의 내용 질문 입력
    ↓
백엔드가 강의자료 검색 + Claude AI로 답변 생성
    ↓
사이드바에 답변 + 출처(몇 페이지) 표시
    ↓
좋아요 / 별로에요 피드백
```

---

## 현재 상태

| 항목 | 상태 | 담당 |
|------|------|------|
| FastAPI 백엔드 | ✅ 완료 | 백엔드팀 |
| Claude RAG 엔진 | ✅ 완료 | 백엔드팀 |
| Extension 파일 구조 + 스켈레톤 | ✅ 완료 | 미리 작업됨 |
| Extension UI/로직 완성 | ⬜ 남음 | **너** |
| `GET /courses` API | ⬜ 남음 | 백엔드팀에 요청 필요 |

---

## 파일 구조

```
extension/
  manifest.json   ← Chrome Extension 설정 (건드릴 필요 거의 없음)
  background.js   ← 백엔드 API 호출 담당 (서비스 워커)
  content.js      ← e-Class 페이지에 사이드바를 심는 스크립트
  panel.html      ← 사이드바 화면 구조
  panel.css       ← 스타일
  panel.js        ← 사이드바 동작 로직 (여기가 주요 작업 공간)
  icons/          ← ⚠️ 아이콘 이미지 직접 추가 필요 (없으면 설치 안 됨)
    icon16.png
    icon48.png
    icon128.png
```

---

## Extension 설치 방법 (개발 중 테스트)

1. 백엔드 서버 먼저 켜기
   ```bash
   uvicorn app.main:app --reload
   ```

2. Chrome 주소창에 `chrome://extensions/` 입력

3. 오른쪽 상단 **개발자 모드** 토글 켜기

4. **"압축 해제된 확장 프로그램 로드"** 클릭 → `extension/` 폴더 선택

5. [e-Class](https://eclass.hufs.ac.kr) 접속하면 오른쪽에 사이드바 자동 표시

> 코드 수정 후에는 `chrome://extensions/`에서 새로고침 버튼(↺) 눌러야 반영됨

---

## 처음 사용 흐름 (사용자 입장)

```
1. e-Class 로그인
2. 사이드바에 학번 입력 → 저장
3. "동기화" 버튼 클릭 → 강의자료 백엔드에 저장됨
4. 과목 페이지로 이동 → 사이드바가 현재 과목 자동 인식
5. 질문 입력 → AI 답변 + 출처 확인
6. 좋아요 / 별로에요 피드백
```

---

## API 명세 (백엔드와 통신하는 방법)

모든 요청은 `http://localhost:8000` 으로 보냅니다.

---

### 동기화 — `POST /sync`

강의자료를 e-Class에서 긁어와서 DB에 저장합니다.

**요청**
```json
{
  "lms_id": "202501718",
  "cookie_str": "JSESSIONID=abc123xyz"
}
```

- `lms_id`: 학번
- `cookie_str`: 브라우저 쿠키에서 자동 추출 (`chrome.cookies` API 사용, 직접 입력 X)

**응답**
```json
{
  "status": "ok",
  "user_id": 1,
  "courses": 7,
  "materials": 79,
  "activities": 20
}
```

- `user_id`: 이후 모든 채팅 요청에 필요하니 `chrome.storage.local`에 저장해두기

---

### 채팅 — `POST /chat`

질문을 보내면 강의자료 검색 후 Claude AI 답변을 돌려줍니다.

**요청**
```json
{
  "user_id": 1,
  "course_id": 3,
  "question": "CNN이 뭐야?"
}
```

- `course_id`: 현재 보고 있는 과목 ID (없어도 되지만 있으면 답변 품질이 훨씬 좋아짐)

**응답**
```json
{
  "session_id": 12,
  "chat_id": 45,
  "answer": "CNN은 Convolutional Neural Network로...",
  "sources": [
    { "chunk_id": 42, "material_id": 7, "page_ref": 5 },
    { "chunk_id": 43, "material_id": 7, "page_ref": 6 }
  ]
}
```

- `session_id`: 이 과목의 대화 세션 ID — 저장해뒀다가 히스토리 조회에 사용
- `sources`: 답변 근거가 된 강의자료 페이지 목록 → 화면에 "5p", "6p" 식으로 표시

---

### 채팅 히스토리 — `GET /chat/{session_id}`

이전 대화를 불러옵니다. 페이지 새로고침 후 복원할 때 사용.

**응답**
```json
[
  { "chat_id": 44, "role": "user",      "content": "CNN이 뭐야?" },
  { "chat_id": 45, "role": "assistant", "content": "CNN은 ..." }
]
```

---

### 피드백 — `POST /chat/{chat_id}/feedback?score=1`

답변에 피드백을 남깁니다.

| score | 의미 |
|-------|------|
| `1`   | 좋아요 |
| `-1`  | 별로에요 |

---

## 과목 자동 인식 원리

e-Class 과목 페이지 URL을 보면:
```
https://eclass.hufs.ac.kr/ilos/st/course/submain_form.acl?ARTL_NUM=A20261T0530120101&...
```

URL의 `ARTL_NUM` 값이 DB에서 과목을 구분하는 `lms_url_id`입니다.  
`content.js`가 URL을 감시하다가 변경되면 `panel.js`에 알려줍니다.

> **문제:** 이 문자열(`A20261T0530120101`)을 DB의 정수형 `course_id`(예: `3`)로 바꾸려면  
> 백엔드에 `GET /courses?user_id=1` API가 필요합니다.  
> **백엔드팀에 요청하고, 완성되면 `panel.js` 안의 TODO 주석을 해제하면 됩니다.**

---

## 데이터 저장 위치

Extension은 `chrome.storage.local`을 씁니다. 저장되는 값들:

| 키 | 내용 | 언제 저장 |
|----|------|----------|
| `lms_id` | 학번 | 학번 입력 후 저장 버튼 |
| `user_id` | DB 유저 ID | 동기화 성공 후 |
| `sessions` | `{ course_id: session_id }` | 채팅할 때마다 갱신 |
| `course_map` | `{ lms_url_id: { course_id, title } }` | GET /courses 구현 후 |

---

## 남은 작업 목록

### 필수
- [ ] `icons/` 폴더에 아이콘 이미지 3개 추가 (`icon16.png`, `icon48.png`, `icon128.png`)
- [ ] 백엔드에 `GET /courses?user_id=X` 추가 요청 → 완료되면 `panel.js` TODO 주석 해제
- [ ] 세션 복원: 새로고침 시 `chrome.storage`에서 `session_id` 읽어 이전 대화 불러오기

### 추가하면 좋은 것
- [ ] 동기화 마지막 시각 표시 ("10분 전 동기화")
- [ ] 답변 텍스트 마크다운 렌더링 (굵기, 목록 등)
- [ ] 출처 태그 클릭 시 해당 강의자료 페이지로 이동
- [ ] 사이드바 너비 드래그 조절

---

## 주의사항

- **JSESSIONID는 코드에 절대 하드코딩 금지** — 반드시 `chrome.cookies` API로만 접근
- e-Class 로그아웃하거나 시간이 지나면 쿠키 만료 → 재로그인 후 동기화 필요
- `background.js`에서만 `chrome.cookies`에 접근 가능 (panel.js 직접 접근 불가)
- `panel.js`에서 API를 직접 fetch하지 말고 `chrome.runtime.sendMessage`로 `background.js`에 위임할 것
