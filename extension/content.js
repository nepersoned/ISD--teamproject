if (!document.getElementById("lms-copilot-root")) {
  const SIDEBAR_WIDTH = "380px";

  const root = document.createElement("div");
  root.id = "lms-copilot-root";
  root.style.cssText = `
    position: fixed;
    top: 0;
    right: 0;
    width: ${SIDEBAR_WIDTH};
    height: 100vh;
    z-index: 2147483647;
    box-shadow: -2px 0 12px rgba(0,0,0,0.15);
    transition: transform 0.2s ease;
  `;

  const iframe = document.createElement("iframe");
  iframe.src = chrome.runtime.getURL("panel.html");
  iframe.style.cssText = "width: 100%; height: 100%; border: none;";
  root.appendChild(iframe);
  document.body.appendChild(root);
  document.body.style.marginRight = SIDEBAR_WIDTH;

  // e-Class 과목 URL에서 lms_url_id 추출
  // 예: ?ARTL_NUM=A20261T0530120101&...
  function getCourseUrlId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("ARTL_NUM") ?? null;
  }

  // iframe 로드 후 초기 과목 ID 전달
  iframe.addEventListener("load", () => {
    iframe.contentWindow.postMessage(
      { type: "URL_CHANGED", courseUrlId: getCourseUrlId() },
      "*"
    );
  });

  // SPA 방식 URL 변경 감지
  let lastUrl = location.href;
  new MutationObserver(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      iframe.contentWindow?.postMessage(
        { type: "URL_CHANGED", courseUrlId: getCourseUrlId() },
        "*"
      );
    }
  }).observe(document, { subtree: true, childList: true });

  // panel에서 사이드바 토글 요청 수신
  window.addEventListener("message", (e) => {
    if (e.data?.type === "TOGGLE_SIDEBAR") {
      const hidden = root.style.transform === "translateX(100%)";
      root.style.transform = hidden ? "" : "translateX(100%)";
      document.body.style.marginRight = hidden ? SIDEBAR_WIDTH : "0";
    }
  });
}
