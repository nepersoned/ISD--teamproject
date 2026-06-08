"""
e-Class → SQLite 동기화 파이프라인
Usage: python -m pipeline.sync
"""
import hashlib
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from scraper.eclass_scraper import EClassScraper, MATERIAL_DIR
from db.db import (
    init_schema, upsert_user, touch_sync,
    upsert_course, upsert_enrollment,
    upsert_material, clear_activities, upsert_activity,
)
from pipeline.chunker import chunk_material

load_dotenv()


def run_sync(lms_id: str = None, cookie_str: str = None) -> dict:
    scraper = EClassScraper(lms_id, cookie_str)

    print("[1/5] 세션 쿠키 주입 및 로그인 검증...")
    if not scraper.login():
        raise RuntimeError(
            "로그인 실패. .env의 ECLASS_COOKIE가 만료됐거나 없습니다.\n"
            "Chrome → F12 → Application → Cookies → JSESSIONID 값을 복사하세요."
        )
    print("      OK")

    print("[2/5] DB 스키마 초기화...")
    init_schema()
    user_id = upsert_user(
        lms_id=scraper.lms_id,
        enc_cookie=scraper.get_session_cookie_str(),
    )
    print(f"      user_id = {user_id}")

    print("[3/5] 수강 과목 목록 수집...")
    courses = scraper.get_courses()
    print(f"      {len(courses)}개 과목")

    total_mat = 0
    total_act = 0

    for course in courses:
        kjkey      = course["kjkey"]
        course_id  = upsert_course(
            lms_url_id=kjkey,
            course_code=course["course_code"],
            title=course["title"],
        )
        upsert_enrollment(user_id, course_id)

        print(f"\n[4/5] {course['title']} ({kjkey})")

        # ── 강의자료 ──────────────────────────────
        materials = scraper.get_materials(kjkey)
        print(f"      자료 {len(materials)}개")
        for mat in materials:
            dest = MATERIAL_DIR / kjkey
            safe = _safe_filename(mat["title"], mat["file_type"])
            local_path = dest / safe

            try:
                # 이미 다운로드된 파일이면 스킵 — 체크섬만 계산해 DB 확인
                if local_path.exists():
                    checksum = hashlib.md5(local_path.read_bytes()).hexdigest()
                else:
                    local_path, checksum = scraper.download_material(
                        mat["download_url"], dest, safe
                    )

                mid = upsert_material(
                    course_id=course_id,
                    title=mat["title"],
                    file_type=mat["file_type"],
                    file_path=str(local_path),
                    checksum=checksum,
                )
                if mid:
                    chunk_material(mid, str(local_path), mat["file_type"])
                total_mat += 1
            except Exception as e:
                print(f"      [WARN] 다운로드 실패: {e}")

        # ── 학습 활동 ─────────────────────────────
        activities = scraper.get_activities(kjkey)
        print(f"      활동 {len(activities)}개")
        clear_activities(user_id, course_id)   # 제출 완료된 항목 포함 전체 초기화
        for act in activities:
            upsert_activity(
                user_id=user_id,
                course_id=course_id,
                title=act["title"],
                status=act["status"],
                due_date=act["due_date"],
            )
            total_act += 1

    print("\n[5/5] 동기화 완료 시각 기록...")
    touch_sync(user_id)
    print("      Done.")

    return {"status": "synced", "user_id": user_id,
            "courses": len(courses), "materials": total_mat, "activities": total_act}


def run_sync_delta(lms_id: str = None, cookie_str: str = None) -> dict:
    """알림 기반 증분 동기화 — 변경된 과목·타입만 처리."""
    scraper = EClassScraper(lms_id, cookie_str)

    if not scraper.login():
        raise RuntimeError("로그인 실패. ECLASS_COOKIE를 확인하세요.")

    init_schema()
    user_id = upsert_user(
        lms_id=scraper.lms_id,
        enc_cookie=scraper.get_session_cookie_str(),
    )

    # 알림 파싱 → 과목별 동기화 대상 결정
    notifications = scraper.get_notifications()
    if not notifications:
        return {"status": "no_changes", "user_id": user_id,
                "courses": 0, "materials": 0, "activities": 0}

    # kjkey → {material, activity} 필요 여부
    targets: dict[str, set] = {}
    for n in notifications:
        targets.setdefault(n["kjkey"], set()).add(n["kind"])

    print(f"[delta] 알림 {len(notifications)}건 → 과목 {len(targets)}개 처리")

    total_mat = 0
    total_act = 0

    for kjkey, kinds in targets.items():
        course_id = upsert_course(lms_url_id=kjkey, course_code="", title=kjkey)
        upsert_enrollment(user_id, course_id)

        if "material" in kinds:
            materials = scraper.get_materials(kjkey)
            print(f"  [{kjkey}] 자료 {len(materials)}개 확인")
            for mat in materials:
                dest      = MATERIAL_DIR / kjkey
                safe      = _safe_filename(mat["title"], mat["file_type"])
                local_path = dest / safe
                try:
                    if local_path.exists():
                        checksum = hashlib.md5(local_path.read_bytes()).hexdigest()
                    else:
                        local_path, checksum = scraper.download_material(
                            mat["download_url"], dest, safe
                        )
                        print(f"  [NEW] {safe}")
                    mid = upsert_material(
                        course_id=course_id, title=mat["title"],
                        file_type=mat["file_type"],
                        file_path=str(local_path), checksum=checksum,
                    )
                    if mid:
                        chunk_material(mid, str(local_path), mat["file_type"])
                    total_mat += 1
                except Exception as e:
                    print(f"  [WARN] {e}")

        if "activity" in kinds:
            activities = scraper.get_activities(kjkey)
            print(f"  [{kjkey}] 활동 {len(activities)}개 확인")
            clear_activities(user_id, course_id)
            for act in activities:
                upsert_activity(
                    user_id=user_id, course_id=course_id,
                    title=act["title"], status=act["status"],
                    due_date=act["due_date"],
                )
                total_act += 1

    touch_sync(user_id)
    return {"status": "delta_synced", "user_id": user_id,
            "courses": len(targets), "materials": total_mat, "activities": total_act}


def _safe_filename(title: str, ext: str) -> str:
    safe = "".join(c if c.isalnum() or c in " ._-가-힣" else "_" for c in title)
    safe = safe.strip()[:80]
    if ext and ext != "unknown" and not safe.lower().endswith(f".{ext}"):
        safe = f"{safe}.{ext}"
    return safe or "file"


if __name__ == "__main__":
    result = run_sync()
    print(result)
