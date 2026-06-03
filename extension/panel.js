// ── 상태 ──────────────────────────────────────────────
const state = {
  userId: null,
  courseUrlId: null,   // URL에서 추출한 lms_url_id (e.g. "A20261T0530120101")
  courseId: null,      // DB의 정수형 course_id
  courseName: "과목 미선택",
  sessionId: null,
  courseMap: {},       // { lms_url_id: { course_id, title } }
};

// ── 초기화 ────────────────────────────────────────────
(async () => {
  const stored = await chrome.storage.local.get(["user_id", "lms_id", "course_map"]);
  state.userId = stored.user_id ?? null;
  state.courseMap = stored.course_map ?? {};

  if (!stored.lms_id) {
    document.getElementById("setup-banner").classList.remove("hidden");
  }
})();

// ── 학번 저장 ─────────────────────────────────────────
document.getElementById("btn-save-id").addEventListener("click", async () => {
  const val = document.getElementById("input-lms-id").value.trim();
  if (!val) return;
  await chrome.storage.local.set({ lms_id: val });
  document.getElementById("setup-banner").classList.add("hidden");
});

// ── 사이드바 닫기 ──────────────────────────────────────
document.getElementById("btn-hide").addEventListener("click", () => {
  window.parent.postMessage({ type: "TOGGLE_SIDEBAR" }, "*");
});

// ── URL 변경 수신 (content.js → panel) ───────────────
window.addEventListener("message", (e) => {
  if (e.data?.type !== "URL_CHANGED") return;
  state.courseUrlId = e.data.courseUrlId;

  if (state.courseUrlId && state.courseMap[state.courseUrlId]) {
    const c = state.courseMap[state.courseUrlId];
    state.courseId = c.course_id;
    state.courseName = c.title;
  } else {
    state.courseId = null;
    state.courseName = state.courseUrlId ? "동기화 필요" : "과목 미선택";
  }
  document.getElementById("course-name").textContent = state.courseName;
  state.sessionId = null;
});

// ── 동기화 ────────────────────────────────────────────
document.getElementById("btn-sync").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sync");
  btn.textContent = "동기화 중...";
  btn.disabled = true;

  const { ok, error, data } = await chrome.runtime.sendMessage({ type: "SYNC" });

  if (!ok) {
    alert(error ?? "동기화 실패. e-Class 로그인 상태를 확인하세요.");
    btn.textContent = "동기화";
    btn.disabled = false;
    return;
  }

  state.userId = data.user_id;

  // TODO: GET /courses?user_id=X 백엔드 구현 후 아래 주석 해제
  // const courseRes = await chrome.runtime.sendMessage({ type: "GET_COURSES" });
  // if (courseRes.ok) {
  //   state.courseMap = courseRes.data;
  //   // URL_CHANGED 재처리로 과목명 갱신
  //   if (state.courseUrlId && state.courseMap[state.courseUrlId]) {
  //     const c = state.courseMap[state.courseUrlId];
  //     state.courseId = c.course_id;
  //     state.courseName = c.title;
  //     document.getElementById("course-name").textContent = state.courseName;
  //   }
  // }

  btn.textContent = `완료 (${data.courses}개 과목)`;
  setTimeout(() => {
    btn.textContent = "동기화";
    btn.disabled = false;
  }, 2000);
});

// ── 채팅 전송 ─────────────────────────────────────────
document.getElementById("btn-send").addEventListener("click", sendMessage);
document.getElementById("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) sendMessage();
});

async function sendMessage() {
  const inputEl = document.getElementById("input");
  const question = inputEl.value.trim();
  if (!question) return;

  if (!state.userId) {
    alert("먼저 학번을 입력하고 동기화를 실행해주세요.");
    return;
  }

  inputEl.value = "";
  document.getElementById("btn-send").disabled = true;

  appendMessage("user", question);
  const typingEl = appendTyping();

  const { ok, data, error } = await chrome.runtime.sendMessage({
    type: "CHAT",
    question,
    course_id: state.courseId ?? null,
  });

  typingEl.remove();

  if (!ok) {
    appendMessage("assistant", `오류: ${error ?? "서버 연결 실패"}`);
  } else {
    if (data.session_id) state.sessionId = data.session_id;
    appendAssistantMessage(data.chat_id, data.answer, data.sources ?? []);
  }

  document.getElementById("btn-send").disabled = false;
  inputEl.focus();
}

// ── DOM 헬퍼 ──────────────────────────────────────────
function appendMessage(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  document.getElementById("messages").appendChild(el);
  scrollBottom();
  return el;
}

function appendTyping() {
  const el = document.createElement("div");
  el.className = "msg assistant typing";
  el.textContent = "답변 생성 중...";
  document.getElementById("messages").appendChild(el);
  scrollBottom();
  return el;
}

function appendAssistantMessage(chatId, text, sources) {
  const el = document.createElement("div");
  el.className = "msg assistant";

  const textEl = document.createElement("p");
  textEl.textContent = text;
  el.appendChild(textEl);

  if (sources.length > 0) {
    const sourcesEl = document.createElement("div");
    sourcesEl.className = "sources";
    sources.forEach((s) => {
      const tag = document.createElement("span");
      tag.className = "source-tag";
      tag.textContent = `${s.page_ref}p`;
      sourcesEl.appendChild(tag);
    });
    el.appendChild(sourcesEl);
  }

  const feedbackEl = document.createElement("div");
  feedbackEl.className = "feedback";

  const upBtn = document.createElement("button");
  upBtn.textContent = "좋아요";
  const downBtn = document.createElement("button");
  downBtn.textContent = "별로에요";

  upBtn.onclick = () => sendFeedback(chatId, 1, upBtn, downBtn);
  downBtn.onclick = () => sendFeedback(chatId, -1, upBtn, downBtn);

  feedbackEl.appendChild(upBtn);
  feedbackEl.appendChild(downBtn);
  el.appendChild(feedbackEl);

  document.getElementById("messages").appendChild(el);
  scrollBottom();
}

async function sendFeedback(chatId, score, upBtn, downBtn) {
  upBtn.classList.toggle("active", score === 1);
  downBtn.classList.toggle("active", score === -1);
  upBtn.disabled = true;
  downBtn.disabled = true;

  await chrome.runtime.sendMessage({ type: "FEEDBACK", chat_id: chatId, score });
}

function scrollBottom() {
  const el = document.getElementById("messages");
  el.scrollTop = el.scrollHeight;
}
