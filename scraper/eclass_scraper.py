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
        soup  = BeautifulSoup(content, "lxml")

        rows = soup.select("table tbody tr") or soup.select("table tr")

        items = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            # 제목: 링크(<a>) 직접 텍스트 우선, 숫자만인 경우는 번호 컬럼이므로 스킵
            BADGE_RE = re.compile(
                r'\s*(퀴즈|온라인\s*시험|오프라인\s*시험|퀴즈온라인\s*시험|'
                r'퀴즈오프라인\s*시험|온라인|오프라인|팀장제출|개별제출|'
                r'팀\s*미지정|진행중|종료)\s*$'
            )
            title = ""
            for col in cols:
                a = col.find("a")
                if a:
                    # 직접 텍스트 노드만 사용 (자식 span 뱃지 제외)
                    raw = "".join(a.find_all(string=True, recursive=False)).strip()
                    if not raw:
                        raw = a.get_text(strip=True)
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
            # 날짜 패턴(YYYY-MM-DD 또는 YYYY.MM.DD)이 있는 열에서 마감일 추출
            due_date = None
            for col in reversed(cols):
                due_date = self._parse_date(col.get_text(strip=True))
                if due_date:
                    break
            items.append({
                "title":    f"[{kind}] {title}",
                "status":   self._parse_status(row),
                "due_date": due_date,
            })
        return items

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
        text = row.get_text().lower()
        if "제출완료" in text or "완료" in text:
            return "completed"
        if "미제출" in text or "미완료" in text:
            return "pending"
        return "unknown"

    @staticmethod
    def _parse_date(raw: str) -> str | None:
        m = re.search(r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})", raw)
        return re.sub(r"[./]", "-", m.group(1)) if m else None
