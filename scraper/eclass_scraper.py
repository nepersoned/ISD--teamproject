"""
HUFS e-Class scraper (cookie-injection, AJAX-aware).

로그인:
  HUFS WIS는 2FA라 자동 로그인 불가.
  Chrome → e-Class 로그인 → F12 → Application → Cookies → JSESSIONID 복사
  .env 파일에 ECLASS_COOKIE=JSESSIONID=... 로 설정.

과목 목록:
  POST /ilos/st/main/course_ing_list.acl  (AJAX)
  <tr id="{KJKEY}" org_sect=".." ledg_year=".." ...>

강의자료:
  POST /ilos/st/course/lecture_material_list.acl (KJKEY 포함)
  또는 eclass_room2.acl 내부 콘텐츠 파싱
"""
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_URL    = "https://eclass.hufs.ac.kr"
COURSE_AJAX = f"{BASE_URL}/ilos/st/main/course_ing_list.acl"
MATERIAL_DIR = Path("data/materials")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
}


class EClassScraper:
    def __init__(self, lms_id: str = None, cookie_str: str = None):
        self.lms_id        = lms_id or os.getenv("ECLASS_ID")
        self._cookie       = cookie_str or os.getenv("ECLASS_COOKIE", "")
        self.session       = requests.Session()
        self.session.headers.update(HEADERS)
        self._logged_in    = False
        self._current_kjkey = None  # _enter_course 중복 호출 방지

    # ------------------------------------------------------------------
    # 세션 주입
    # ------------------------------------------------------------------

    def login(self) -> bool:
        if not self._cookie:
            raise ValueError("ECLASS_COOKIE 없음. .env에 JSESSIONID 값을 넣으세요.")

        for pair in self._cookie.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, _, value = pair.partition("=")
                self.session.cookies.set(
                    name.strip(), value.strip(), domain="eclass.hufs.ac.kr"
                )

        # 메인 페이지 로드 — 세션 유효성 확인
        self.session.get(f"{BASE_URL}/ilos/main/main_form.acl", timeout=15)

        resp = self.session.post(
            COURSE_AJAX,
            data={"SCH_VALUE": "", "SCH_ORG_SECT": "", "start": "", "encoding": "utf-8"},
            timeout=15,
        )
        # 로그인 페이지로 리다이렉트되지 않으면 성공
        self._logged_in = "login_form" not in resp.url and len(resp.content) > 500
        return self._logged_in

    def get_session_cookie_str(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.session.cookies.items())

    # ------------------------------------------------------------------
    # 과목 목록 (메인 페이지 파싱)
    # ------------------------------------------------------------------

    def get_courses(self) -> list[dict]:
        """
        메인 페이지의 '수강과목' 섹션에서 em.sub_open[kj] 요소를 파싱.
        Return list of: {kjkey, course_code, title}
        """
        resp = self.session.get(
            f"{BASE_URL}/ilos/main/main_form.acl", timeout=15
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")

        courses = []
        seen = set()
        for em in soup.select("em.sub_open[kj]"):
            kjkey = em.get("kj", "").strip()
            if not kjkey or kjkey in seen:
                continue
            seen.add(kjkey)

            # title attr: "과목명 강의실 들어가기"
            title_attr = em.get("title", "")
            title = re.sub(r"\s*강의실\s*들어가기.*$", "", title_attr).strip()

            # inner text 첫 줄: "[캠퍼스]과목명", 두 번째 줄: "(과목코드-분반)"
            lines = [l.strip() for l in em.get_text("\n").split("\n") if l.strip()]
            # 캠퍼스 태그 제거
            if title:
                clean_title = re.sub(r"^\[.*?\]", "", title).strip()
            else:
                clean_title = re.sub(r"^\[.*?\]", "", lines[0] if lines else "").strip()

            # 과목코드: "(코드-분반)" 형태
            code_raw = next((l for l in lines if re.match(r"^\(.+\)$", l)), "")
            course_code = code_raw.strip("()")

            courses.append({
                "kjkey":       kjkey,
                "course_code": course_code,
                "title":       clean_title,
            })

        return courses

    # ------------------------------------------------------------------
    # 과목 강의실 진입 (세션에 course context 설정)
    # ------------------------------------------------------------------

    def _enter_course(self, kjkey: str) -> bool:
        """eclass_room2.acl → returnURL GET → 세션에 과목 컨텍스트 설정."""
        if self._current_kjkey == kjkey:
            return True
        resp = self.session.post(
            f"{BASE_URL}/ilos/st/course/eclass_room2.acl",
            data={
                "KJKEY": kjkey,
                "returnData": "json",
                "returnURI": "/ilos/st/course/submain_form.acl",
                "encoding": "utf-8",
            },
            timeout=15,
        )
        try:
            data = resp.json()
        except Exception:
            return False
        if data.get("isError"):
            return False
        return_url = data.get("returnURL", "")
        if return_url:
            self.session.get(urljoin(BASE_URL, return_url), timeout=15)
        self._current_kjkey = kjkey
        return True

    # ------------------------------------------------------------------
    # 강의자료
    # ------------------------------------------------------------------

    def get_materials(self, kjkey: str) -> list[dict]:
        """강의자료 목록 수집 → efile_download2.acl 링크 파싱."""
        if not self._enter_course(kjkey):
            return []

        # 강의자료 AJAX 목록 (JS와 동일한 파라미터)
        resp = self.session.post(
            f"{BASE_URL}/ilos/st/course/lecture_material_list.acl",
            data={"start": "0", "display": "1", "SCH_VALUE": "",
                  "ud": self.lms_id, "ky": kjkey, "encoding": "utf-8"},
            timeout=15,
        )
        resp.raise_for_status()

        # downloadClick('HASH') 패턴에서 content_seq 해시 추출
        hash_keys = re.findall(r"downloadClick\('([A-Z0-9]+)'\)", resp.text)

        materials = []
        for hk in hash_keys[:20]:
            file_resp = self.session.post(
                f"{BASE_URL}/ilos/co/list_file_list2.acl",
                data={"ud": self.lms_id, "ky": kjkey,
                      "pf_st_flag": "2", "CONTENT_SEQ": hk,
                      "encoding": "utf-8"},
                timeout=15,
            )
            file_soup = BeautifulSoup(file_resp.content, "lxml")
            # 파일 링크는 onclick에 efile_download2.acl URL 포함
            for a in file_soup.find_all("a"):
                onclick = a.get("onclick", "")
                m = re.search(r"location\.href='(/ilos/co/efile_download2\.acl[^']+)'", onclick)
                if not m:
                    continue
                dl_path = m.group(1)
                fname   = a.get_text(strip=True)
                ext     = self._guess_ext(fname, dl_path)
                materials.append({
                    "title":        fname or f"material_{hk}",
                    "file_type":    ext if ext != "unknown" else "bin",
                    "download_url": urljoin(BASE_URL, dl_path),
                    "artl_num":     hk,
                })

        return materials

    def download_material(
        self, download_url: str, dest_dir: Path, filename: str
    ) -> tuple[Path, str]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        local_path = dest_dir / filename
        resp = self.session.get(download_url, stream=True, timeout=30)
        resp.raise_for_status()
        md5 = hashlib.md5()
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                md5.update(chunk)
        return local_path, md5.hexdigest()

    # ------------------------------------------------------------------
    # 학습 활동 (과제 / 퀴즈)
    # ------------------------------------------------------------------

    def get_activities(self, kjkey: str) -> list[dict]:
        if not self._enter_course(kjkey):
            return []

        activities = []

        # 과제/팀프로젝트: 실제 데이터는 AJAX POST 엔드포인트에 있음
        for kind, path in [
            ("assignment", "/ilos/st/course/report_list.acl"),
            ("project",    "/ilos/st/course/project_list.acl"),
        ]:
            try:
                resp = self.session.post(
                    BASE_URL + path,
                    data={"start": "0", "display": "1", "SCH_VALUE": "",
                          "ud": self.lms_id, "ky": kjkey, "encoding": "utf-8"},
                    timeout=15,
                )
                resp.raise_for_status()
                activities += self._parse_activity_list(resp.content, kind)
            except Exception:
                pass

        # 퀴즈: test_list_form.acl 은 HTML 테이블을 직접 포함
        try:
            resp = self.session.get(
                BASE_URL + "/ilos/st/course/test_list_form.acl", timeout=15
            )
            resp.raise_for_status()
            activities += self._parse_activity_list(resp.content, "quiz")
        except Exception:
            pass

        return activities

    def _parse_activity_list(self, content: bytes, kind: str) -> list[dict]:
        soup = BeautifulSoup(content, "lxml")
        rows = soup.find_all("tr")

        BADGE_RE = re.compile(
            r'\s*(퀴즈|온라인\s*시험|오프라인\s*시험|온라인|오프라인|'
            r'팀장제출|개별제출|팀\s*미지정|진행중|종료)\s*$'
        )
        items = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            # ── 제목 + detail URL: pageMove() 가 있는 <td onclick> ──
            title = ""
            detail_url = None
            for col in cols:
                onclick = col.get("onclick", "")
                m = re.search(r"pageMove\s*\(\s*['\"]([^'\"]+)['\"]", onclick)
                if m:
                    detail_url = urljoin(BASE_URL, m.group(1))
                    # 제목은 .subjt_top 또는 <a> 텍스트
                    st = col.select_one(".subjt_top")
                    raw = st.get_text(strip=True) if st else col.find("a") and col.find("a").get_text(strip=True) or ""
                    if not raw:
                        raw = col.get_text(strip=True)
                    title = BADGE_RE.sub("", raw).strip()
                    break

            # pageMove 없으면 기존 방식 fallback
            if not title:
                for col in cols:
                    a = col.find("a")
                    if a:
                        raw = "".join(a.find_all(string=True, recursive=False)).strip() or a.get_text(strip=True)
                        raw = BADGE_RE.sub("", raw).strip()
                        if len(raw) > 1 and not raw.isdigit():
                            title = raw
                            break
                    else:
                        t = col.get_text(strip=True)
                        if len(t) > 1 and not t.isdigit():
                            title = t
                            break

            if not title:
                continue

            # ── 마감일 ──
            due_date = None
            for col in reversed(cols):
                due_date = self._parse_date(col.get_text(strip=True))
                if due_date:
                    break

            items.append({
                "title":      f"[{kind}] {title}",
                "status":     self._parse_status(row),
                "due_date":   due_date,
                "detail_url": detail_url,
            })
        return items

    def _extract_detail_url(self, a_tag, kind: str) -> str | None:
        """<a> 태그에서 상세 페이지 URL 추출 — 다양한 e-Class 패턴 처리."""
        href    = a_tag.get("href", "")
        onclick = a_tag.get("onclick", "")
        combined = href + " " + onclick

        # 1) href가 실제 /ilos 경로
        if href and href.startswith("/ilos"):
            return urljoin(BASE_URL, href)

        # 2) location.href 패턴
        m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", combined)
        if m:
            return urljoin(BASE_URL, m.group(1))

        # 3) goSubjectPage('KJKEY', 'ARTL_NUM', ...) — 알림과 동일 패턴
        m = re.search(r"goSubjectPage\s*\(\s*['\"]?(\w+)['\"]?\s*,\s*['\"]?(\w+)['\"]?", combined)
        if m:
            artl_num = m.group(2)
            return self._build_detail_url(kind, artl_num)

        # 4) 모든 JS 함수 — 두 번째 인자가 숫자인 경우 ARTL_NUM으로 취급
        m = re.search(r"\w+\s*\(['\"]?\w+['\"]?\s*,\s*['\"]?(\d{4,})['\"]?", combined)
        if m:
            return self._build_detail_url(kind, m.group(1))

        # 5) 함수 첫 번째 인자가 숫자
        m = re.search(r"\w+\s*\(\s*['\"]?(\d{4,})['\"]?", combined)
        if m:
            return self._build_detail_url(kind, m.group(1))

        return None

    def _build_detail_url(self, kind: str, artl_num: str) -> str | None:
        path_map = {
            "assignment": f"/ilos/st/course/report_detail_form.acl?ud={self.lms_id}&ky={self._current_kjkey}&ARTL_NUM={artl_num}&encoding=utf-8",
            "project":    f"/ilos/st/course/project_detail_form.acl?ud={self.lms_id}&ky={self._current_kjkey}&ARTL_NUM={artl_num}&encoding=utf-8",
            "quiz":       f"/ilos/st/course/test_detail_form.acl?ud={self.lms_id}&ky={self._current_kjkey}&ARTL_NUM={artl_num}&encoding=utf-8",
        }
        path = path_map.get(kind)
        return urljoin(BASE_URL, path) if path else None

    def get_activity_detail(self, url: str) -> str | None:
        """상세 페이지에서 과제/프로젝트 설명 텍스트 추출."""
        if not url:
            return None
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            # 세션 만료 체크 (리다이렉트만)
            if "login_form" in resp.url or "main_form" in resp.url:
                return None
            soup = BeautifulSoup(resp.content, "lxml")

            # 우선순위 순 셀렉터
            for sel in [
                ".view_cont", ".cont_area", ".board_view_cont",
                "td.view_cont", "div.content", ".detail_content",
                "td[class*='cont']", "div[class*='view']", "div[class*='detail']",
                "#contentArea", ".contentArea",
            ]:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(" ", strip=True)
                    if len(text) > 20:
                        return text[:1500]

            # fallback: 가장 긴 <td>
            tds = [t for t in soup.find_all("td") if len(t.get_text(strip=True)) > 30]
            if tds:
                longest = max(tds, key=lambda t: len(t.get_text(strip=True)))
                text = longest.get_text(" ", strip=True)
                if len(text) > 20:
                    return text[:1500]
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # 공지사항 (notice_list.acl)
    # ------------------------------------------------------------------

    def get_notices(self, kjkey: str) -> list[dict]:
        """공지사항 목록 + 본문 수집. [{title, content, artl_num}]"""
        if not self._enter_course(kjkey):
            return []
        try:
            resp = self.session.post(
                f"{BASE_URL}/ilos/st/course/notice_list.acl",
                data={"start": "0", "display": "1", "SCH_VALUE": "",
                      "ud": self.lms_id, "ky": kjkey, "encoding": "utf-8"},
                timeout=15,
            )
            resp.raise_for_status()
        except Exception:
            return []

        soup = BeautifulSoup(resp.content, "lxml")
        notices = []
        for row in soup.find_all("tr"):
            for col in row.find_all("td"):
                onclick = col.get("onclick", "")
                m = re.search(r"pageMove\s*\(\s*['\"]([^'\"]+)['\"]", onclick)
                if not m:
                    continue
                detail_url = urljoin(BASE_URL, m.group(1))
                artl_m = re.search(r"ARTL_NUM=(\d+)", detail_url)
                artl_num = artl_m.group(1) if artl_m else ""

                st = col.select_one("div:not(.subjt_b)")
                title = st.get_text(strip=True) if st else col.get_text(strip=True)[:80]
                title = title.strip()

                content = self.get_activity_detail(detail_url) or ""
                if title:
                    notices.append({
                        "title":    title,
                        "content":  f"[공지] {title}\n{content}",
                        "artl_num": artl_num,
                    })
                break  # td 하나만
        return notices

    # ------------------------------------------------------------------
    # 알림 (notification_list.acl)
    # ------------------------------------------------------------------

    def get_notifications(self) -> list[dict]:
        """
        e-Class 알림 목록 파싱.
        Return list of: {kjkey, artl_num, kind, text}
        kind: 'material' | 'activity'
        """
        resp = self.session.post(
            f"{BASE_URL}/ilos/mp/notification_list.acl",
            data={"start": "0", "openDt": "", "encoding": "utf-8"},
            timeout=15,
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "lxml")

        KIND_MAP = {
            "강의자료":  "material",
            "과제":     "activity",
            "시험":     "activity",
            "퀴즈":     "activity",
            "온라인강의": "activity",
            "팀프로젝트": "activity",
        }

        notifications = []
        for div in soup.select("div.notification_content[onclick]"):
            m = re.search(r"goSubjectPage\('(\w+)','(\d+)','S'\)", div.get("onclick", ""))
            if not m:
                continue
            kjkey, artl_num = m.group(1), m.group(2)

            kind_span = div.select_one("span.site-font-color")
            raw_kind  = kind_span.get_text(strip=True).strip("[]") if kind_span else ""
            kind      = KIND_MAP.get(raw_kind)
            if not kind:
                continue

            text = div.select_one("div.notification_text")
            text = text.get_text(" ", strip=True) if text else ""

            notifications.append({
                "kjkey":    kjkey,
                "artl_num": artl_num,
                "kind":     kind,
                "text":     text,
            })

        return notifications

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _guess_ext(title: str, href: str) -> str:
        for src in (title, href):
            m = re.search(
                r"\.(pdf|ppt|pptx|doc|docx|xls|xlsx|zip|mp4|hwp)$",
                src, re.IGNORECASE
            )
            if m:
                return m.group(1).lower()
        return "unknown"

    @staticmethod
    def _parse_status(row) -> str:
        # 1) <img alt="미제출"> / <img alt="제출"> 패턴 (e-Class 실제 구조)
        for img in row.find_all("img"):
            alt = img.get("alt", "").strip()
            if any(kw in alt for kw in ("미제출", "미완료", "미응시")):
                return "pending"
            if any(kw in alt for kw in ("제출", "완료", "응시")):
                return "completed"
        # 2) 텍스트 fallback — 부정 먼저
        text = row.get_text()
        if any(kw in text for kw in ("미제출", "미완료", "미응시", "미참여")):
            return "pending"
        if any(kw in text for kw in ("제출완료", "완료", "응시완료", "출석완료")):
            return "completed"
        return "unknown"

    @staticmethod
    def _parse_date(raw: str) -> str | None:
        m = re.search(r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})", raw)
        return re.sub(r"[./]", "-", m.group(1)) if m else None
