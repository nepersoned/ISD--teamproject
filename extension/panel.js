// ── 상태 ──────────────────────────────────────────────
const state = {
  userId: null,
  courseUrlId: null,
  courseId: null,
  courseName: "과목 미선택",
  sessionId: null,
  courseMap: {},
  messages: [], // 대화 내용 메모리 캐시
};

// ── 상대 시간 표시 ─────────────────────────────────────
function timeAgo(ts) {
  const diff = Math.floor((Date.now() - ts) / 1000);
  if (diff < 60) return "방금 동기화";
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전 동기화`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전 동기화`;
  return `${Math.floor(diff / 86400)}일 전 동기화`;
}

function updateSyncLabel(ts) {
  const btn = document.getElementById("btn-sync");
  btn.textContent = timeAgo(ts);
}

// ── 초기화 ────────────────────────────────────────────
(async () => {
  const stored = await chrome.storage.local.get([
    "user_id", "lms_id", "course_map", "last_sync_at", "messages", "session_id"
  ]);

  state.userId = stored.user_id ?? null;
  state.courseMap = stored.course_map ?? {};
  state.sessionId = stored.session_id ?? null;

  // 동기화 버튼 초기 상태
  if (stored.last_sync_at) {
    updateSyncLabel(stored.last_sync_at);
    setInterval(() => updateSyncLabel(stored.last_sync_at), 60000);
  }

  // 저장된 학번 없으면 배너 표시
  if (!stored.lms_id) {
    document.getElementById("setup-banner").classList.remove("hidden");
  }

  // 저장된 대화 복원
  if (stored.messages && stored.messages.length > 0) {
    state.messages = stored.messages;
    hideEmptyState();
    stored.messages.forEach((msg) => {
      if (msg.role === "user") {
        renderMessage("user", msg.content);
      } else {
        renderAssistantMessage(msg.chatId, msg.content, msg.sources ?? []);
      }
    });
  }
})();

// ── 학번 저장 ─────────────────────────────────────────
document.getElementById("btn-save-id").addEventListener("click", async () => {
  const val = document.getElementById("input-lms-id").value.trim();
  if (!val) return;
  await chrome.storage.local.set({ lms_id: val });
  document.getElementById("setup-banner").classList.add("hidden");
});

// ── 닫기 ──────────────────────────────────────────────
document.getElementById("btn-hide").addEventListener("click", () => {
  window.parent.postMessage({ type: "TOGGLE_SIDEBAR" }, "*");
});

// ── 새 채팅 ───────────────────────────────────────────
document.getElementById("btn-new-chat").addEventListener("click", async () => {
  state.sessionId = null;
  state.messages = [];
  await chrome.storage.local.remove(["session_id", "messages"]);

  const msgs = document.getElementById("messages");
  msgs.innerHTML = `
    <div id="empty-state">
      <p class="empty-title">무엇이든 물어보세요</p>
      <p class="empty-desc">동기화된 강의자료를 기반으로<br>답변해드려요</p>
      <div id="hints">
        <button class="hint-chip">이번 주 과제 마감일이 언제야?</button>
        <button class="hint-chip">강의 핵심 개념 요약해줘</button>
        <button class="hint-chip">시험 범위 알려줘</button>
      </div>
    </div>`;

  document.querySelectorAll(".hint-chip").forEach((chip) => {
    chip.addEventListener("click", () => sendMessage(chip.textContent));
  });
});

// ── URL 변경 수신 ─────────────────────────────────────
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
});

// ── 동기화 ────────────────────────────────────────────
document.getElementById("btn-sync").addEventListener("click", async () => {
  const btn = document.getElementById("btn-sync");
  btn.textContent = "동기화 중...";
  btn.disabled = true;

  const { ok, error, data } = await chrome.runtime.sendMessage({ type: "SYNC" });

  if (!ok) {
    alert(error ?? "동기화 실패. e-Class에 로그인되어 있는지 확인하세요.");
    btn.textContent = "동기화";
    btn.disabled = false;
    return;
  }

  state.userId = data.user_id;

  // 과목 목록 가져와서 저장
  const courseRes = await chrome.runtime.sendMessage({ type: "GET_COURSES" });
  if (courseRes.ok && courseRes.data) {
    state.courseMap = courseRes.data;
    await chrome.storage.local.set({ course_map: courseRes.data });
  }

  const now = Date.now();
  await chrome.storage.local.set({ last_sync_at: now });
  updateSyncLabel(now);
  setInterval(() => updateSyncLabel(now), 60000);
  btn.disabled = false;
});

// ── 힌트 칩 ──────────────────────────────────────────
document.querySelectorAll(".hint-chip").forEach((chip) => {
  chip.addEventListener("click", () => sendMessage(chip.textContent));
});

// ── 채팅 전송 ─────────────────────────────────────────
document.getElementById("btn-send").addEventListener("click", () => sendMessage());

const inputEl = document.getElementById("input");
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
inputEl.addEventListener("input", () => {
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
});

async function sendMessage(question) {
  const q = (question ?? inputEl.value).trim();
  if (!q) return;

  if (!state.userId) {
    alert("먼저 학번을 입력하고 동기화를 실행해주세요.");
    return;
  }

  hideEmptyState();
  inputEl.value = "";
  inputEl.style.height = "auto";
  document.getElementById("btn-send").disabled = true;

  renderMessage("user", q);

  const { wrap, textEl, el } = appendStreamBubble();

  let fullText = "";
  let chatId = null;
  let sources = [];

  try {
    const res = await fetch("http://localhost:8001/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: state.userId,
        course_id: state.courseId ?? null,
        question: q,
        session_id: state.sessionId ?? null,
      }),
    });

    if (!res.ok) {
      textEl.innerHTML = `<p>오류: 서버 연결 실패 (${res.status})</p>`;
    } else {
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.delta) {
              fullText += data.delta;
              textEl.innerHTML = "<p>" + renderMarkdown(fullText) + "</p>";
              scrollBottom();
            }
            if (data.done) {
              chatId = data.chat_id;
              sources = data.sources ?? [];
              state.sessionId = data.session_id;
              await chrome.storage.local.set({ session_id: data.session_id });
            }
            if (data.error) {
              textEl.innerHTML = `<p>오류: ${data.error}</p>`;
            }
          } catch (_) {}
        }
      }
    }
  } catch (err) {
    textEl.innerHTML = `<p>오류: ${err.message}</p>`;
  }

  // 스트리밍 완료 후 출처 + 피드백 추가
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

  if (chatId) {
    const feedbackEl = document.createElement("div");
    feedbackEl.className = "feedback";
    const upBtn = document.createElement("button");
    upBtn.textContent = "👍 도움됐어요";
    const downBtn = document.createElement("button");
    downBtn.textContent = "👎 별로에요";
    upBtn.onclick = () => sendFeedback(chatId, 1, upBtn, downBtn);
    downBtn.onclick = () => sendFeedback(chatId, -1, upBtn, downBtn);
    feedbackEl.appendChild(upBtn);
    feedbackEl.appendChild(downBtn);
    el.appendChild(feedbackEl);
  }

  state.messages.push({ role: "user", content: q });
  state.messages.push({ role: "assistant", content: fullText, chatId, sources });
  await chrome.storage.local.set({ messages: state.messages });

  document.getElementById("btn-send").disabled = false;
  inputEl.focus();
}

// ── DOM 헬퍼 ──────────────────────────────────────────
function hideEmptyState() {
  const el = document.getElementById("empty-state");
  if (el) el.remove();
}

function renderMessage(role, text) {
  const wrap = document.createElement("div");
  wrap.style.cssText = `display:flex; flex-direction:column; align-items:${role === "user" ? "flex-end" : "flex-start"}; gap:4px;`;

  if (role === "assistant") {
    const label = document.createElement("span");
    label.className = "msg-label";
    label.textContent = "Copilot";
    wrap.appendChild(label);
  }

  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.textContent = text;
  wrap.appendChild(el);

  document.getElementById("messages").appendChild(wrap);
  scrollBottom();
  return wrap;
}

function appendStreamBubble() {
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex; flex-direction:column; align-items:flex-start; gap:4px;";

  const label = document.createElement("span");
  label.className = "msg-label";
  label.textContent = "Copilot";
  wrap.appendChild(label);

  const el = document.createElement("div");
  el.className = "msg assistant";

  const textEl = document.createElement("div");
  textEl.className = "msg-body";
  textEl.innerHTML = `<div class="typing-dots"><span></span><span></span><span></span></div>`;
  el.appendChild(textEl);
  wrap.appendChild(el);

  document.getElementById("messages").appendChild(wrap);
  scrollBottom();
  return { wrap, textEl, el };
}

function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^### (.+)$/gm, "<strong>$1</strong>")
    .replace(/^## (.+)$/gm, "<strong>$1</strong>")
    .replace(/^# (.+)$/gm, "<strong>$1</strong>")
    .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/gs, "<ul>$1</ul>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>");
}

function renderAssistantMessage(chatId, text, sources) {
  const wrap = document.createElement("div");
  wrap.style.cssText = "display:flex; flex-direction:column; align-items:flex-start; gap:4px;";

  const label = document.createElement("span");
  label.className = "msg-label";
  label.textContent = "Copilot";
  wrap.appendChild(label);

  const el = document.createElement("div");
  el.className = "msg assistant";

  const textEl = document.createElement("div");
  textEl.className = "msg-body";
  textEl.innerHTML = "<p>" + renderMarkdown(text) + "</p>";
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

  if (chatId) {
    const feedbackEl = document.createElement("div");
    feedbackEl.className = "feedback";
    const upBtn = document.createElement("button");
    upBtn.textContent = "👍 도움됐어요";
    const downBtn = document.createElement("button");
    downBtn.textContent = "👎 별로에요";
    upBtn.onclick = () => sendFeedback(chatId, 1, upBtn, downBtn);
    downBtn.onclick = () => sendFeedback(chatId, -1, upBtn, downBtn);
    feedbackEl.appendChild(upBtn);
    feedbackEl.appendChild(downBtn);
    el.appendChild(feedbackEl);
  }

  wrap.appendChild(el);
  document.getElementById("messages").appendChild(wrap);
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
