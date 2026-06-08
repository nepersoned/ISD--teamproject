const API = "http://localhost:8001";

async function getSessionCookie() {
  const cookies = await chrome.cookies.getAll({ name: "JSESSIONID" });
  const cookie = cookies.find((c) => c.domain.includes("eclass.hufs.ac.kr"));
  return cookie?.value ?? null;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_COOKIE") {
    getSessionCookie().then((cookie) => sendResponse({ cookie }));
    return true;
  }

  if (msg.type === "SYNC") {
    (async () => {
      const cookie = await getSessionCookie();
      if (!cookie) return sendResponse({ ok: false, error: "쿠키 없음" });

      const { lms_id } = await chrome.storage.local.get("lms_id");
      const res = await fetch(`${API}/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lms_id: lms_id ?? "",
          cookie_str: `JSESSIONID=${cookie}`,
        }),
      });

      if (!res.ok) return sendResponse({ ok: false, error: await res.text() });
      const data = await res.json();
      await chrome.storage.local.set({ user_id: data.user_id });
      sendResponse({ ok: true, data });
    })();
    return true;
  }

  if (msg.type === "GET_COURSES") {
    (async () => {
      const { user_id } = await chrome.storage.local.get("user_id");
      if (!user_id) return sendResponse({ ok: false, error: "동기화 필요" });

      const res = await fetch(`${API}/courses?user_id=${user_id}`);
      if (!res.ok) return sendResponse({ ok: false, error: await res.text() });
      const data = await res.json();
      await chrome.storage.local.set({ course_map: data });
      sendResponse({ ok: true, data });
    })();
    return true;
  }

  if (msg.type === "CHAT") {
    (async () => {
      const { user_id, sessions } = await chrome.storage.local.get([
        "user_id",
        "sessions",
      ]);
      if (!user_id) return sendResponse({ ok: false, error: "동기화 필요" });

      const courseKey = msg.course_id ?? "global";
      const sessionId = (sessions ?? {})[courseKey] ?? null;

      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id,
          course_id: msg.course_id ?? null,
          question: msg.question,
          session_id: sessionId,
        }),
      });

      if (!res.ok) return sendResponse({ ok: false, error: await res.text() });
      const data = await res.json();

      const updated = { ...(sessions ?? {}) };
      updated[courseKey] = data.session_id;
      await chrome.storage.local.set({ sessions: updated });

      sendResponse({ ok: true, data });
    })();
    return true;
  }

  if (msg.type === "HISTORY") {
    (async () => {
      const res = await fetch(`${API}/chat/${msg.session_id}`);
      if (!res.ok) return sendResponse({ ok: false });
      sendResponse({ ok: true, data: await res.json() });
    })();
    return true;
  }

  if (msg.type === "FEEDBACK") {
    fetch(`${API}/chat/${msg.chat_id}/feedback?score=${msg.score}`, {
      method: "POST",
    })
      .then((r) => r.json())
      .then((data) => sendResponse({ ok: true, data }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }

  if (msg.type === "LOG_VIEW") {
    fetch(`${API}/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: msg.user_id,
        course_id: msg.course_id,
        material_id: msg.material_id ?? null,
        stay_time: msg.stay_time,
      }),
    }).catch(() => {});
    return false;
  }
});
