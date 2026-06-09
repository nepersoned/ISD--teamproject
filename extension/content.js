if (!document.getElementById("lms-copilot-root")) {
  const MIN_W = 300;
  const MAX_W = 700;
  const DEFAULT_W = 380;
  const STORAGE_KEY = "lms-copilot-width";

  let width = Math.min(Math.max(parseInt(localStorage.getItem(STORAGE_KEY) || DEFAULT_W), MIN_W), MAX_W);
  let open = true;

  // wrapper
  const root = document.createElement("div");
  root.id = "lms-copilot-root";
  Object.assign(root.style, {
    position: "fixed", top: "0", right: "0",
    width: width + "px", height: "100vh",
    zIndex: "2147483647",
    boxShadow: "-2px 0 20px rgba(0,0,0,0.15)",
    transition: "transform 0.25s cubic-bezier(.4,0,.2,1)",
  });

  // iframe
  const iframe = document.createElement("iframe");
  iframe.src = chrome.runtime.getURL("panel.html");
  Object.assign(iframe.style, { width: "100%", height: "100%", border: "none" });

  root.appendChild(iframe);
  document.body.appendChild(root);
  document.body.style.marginRight = width + "px";

  // toggle button
  const toggle = document.createElement("button");
  toggle.textContent = "AI";
  Object.assign(toggle.style, {
    position: "fixed", top: "50%", right: width + "px",
    transform: "translateY(-50%)",
    zIndex: "2147483645",
    background: "#1a1d2e", color: "#6c8ef7",
    border: "none", borderRadius: "8px 0 0 8px",
    padding: "12px 7px",
    fontSize: "11px", fontWeight: "700",
    fontFamily: "system-ui, sans-serif",
    letterSpacing: "0.1em",
    writingMode: "vertical-rl",
    cursor: "pointer",
    boxShadow: "-2px 0 10px rgba(0,0,0,0.18)",
    transition: "right 0.25s cubic-bezier(.4,0,.2,1), background 0.15s",
  });
  toggle.addEventListener("mouseenter", () => { toggle.style.background = "#252840"; });
  toggle.addEventListener("mouseleave", () => { toggle.style.background = "#1a1d2e"; });
  toggle.addEventListener("click", () => {
    open = !open;
    root.style.transform = open ? "" : "translateX(100%)";
    toggle.style.right = open ? width + "px" : "0";
    document.body.style.marginRight = open ? width + "px" : "0";
  });
  document.body.appendChild(toggle);

  // panel에서 닫기 요청
  window.addEventListener("message", (e) => {
    if (e.data?.type === "TOGGLE_SIDEBAR") {
      open = !open;
      root.style.transform = open ? "" : "translateX(100%)";
      toggle.style.right = open ? width + "px" : "0";
    }
  });

  // 과목 URL 감지
  function getCourseUrlId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("ARTL_NUM") ?? null;
  }

  iframe.addEventListener("load", () => {
    iframe.contentWindow.postMessage({ type: "URL_CHANGED", courseUrlId: getCourseUrlId() }, "*");
  });

  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      iframe.contentWindow?.postMessage({ type: "URL_CHANGED", courseUrlId: getCourseUrlId() }, "*");
    }
  }).observe(document, { subtree: true, childList: true });

  // ── Personal_Log — 체류 시간 측정 ──────────────────
  let pageEnterTime = Date.now();

  async function flushLog() {
    try {
    const stayTime = Math.round((Date.now() - pageEnterTime) / 1000);
    if (stayTime < 5) return;

    const stored = await chrome.storage.local.get(["user_id", "course_map"]);
    const userId = stored.user_id;
    if (!userId) return;

    const kjkey = getCourseUrlId();
    const courseEntry = kjkey && stored.course_map ? stored.course_map[kjkey] : null;
    const courseId = courseEntry?.course_id ?? null;
    if (!courseId) return;

    chrome.runtime.sendMessage({
      type: "LOG_VIEW",
      user_id: userId,
      course_id: courseId,
      material_id: null,
      stay_time: stayTime,
    });
    } catch (_) {}
  }

  // 페이지 이탈 시 전송
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flushLog();
  });
  window.addEventListener("beforeunload", flushLog);
}
