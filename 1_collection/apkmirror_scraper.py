"""
버전 히스토리 수집기 (리뷰 기반 버전 타임라인 추정)

APKMirror는 한국 앱 미등재 + 403 차단 문제로 직접 크롤링 불가.
대신 google-play-scraper 리뷰의 appVersion 필드를 활용해
"첫 등장 날짜 = 출시 날짜 근사값"으로 버전 히스토리를 재구성.

결과: data/raw/versions/{app_id}.json
"""

import time
from datetime import datetime
from pathlib import Path
import json

import pandas as pd
from google_play_scraper import Sort, reviews as gp_reviews

# ───────────────────────────────────────────
# 분석 대상 앱 (수정된 패키지명)
# ───────────────────────────────────────────
APP_LIST = [
    # 배달
    {"app_id": "com.sampleapp",         "name": "배달의민족", "category": "배달"},
    {"app_id": "com.coupang.mobile.eats","name": "쿠팡이츠",   "category": "배달"},
    # 커머스
    {"app_id": "com.coupang.mobile",    "name": "쿠팡",       "category": "커머스"},
    {"app_id": "com.dbs.kurly.m2",      "name": "마켓컬리",   "category": "커머스"},
    # 금융
    {"app_id": "com.kakaobank.channel", "name": "카카오뱅크", "category": "금융"},
    {"app_id": "viva.republica.toss",   "name": "토스",       "category": "금융"},
]

LANG    = "ko"
COUNTRY = "kr"

VERSIONS_DIR = Path(__file__).parent.parent / "data" / "raw" / "versions"


def fetch_reviews_for_versions(app_id: str, max_reviews: int = 10000) -> list[dict]:
    """
    리뷰를 대량 수집해 appVersion 필드 확보.
    NEWEST 정렬로 전 기간을 커버.
    """
    all_reviews = []
    token = None

    while len(all_reviews) < max_reviews:
        try:
            result, token = gp_reviews(
                app_id,
                lang=LANG,
                country=COUNTRY,
                sort=Sort.NEWEST,
                count=200,
                continuation_token=token,
            )
        except Exception as e:
            print(f"  오류: {e}")
            break

        if not result:
            break
        all_reviews.extend(result)

        if token is None:
            break
        if len(all_reviews) % 1000 == 0:
            print(f"  {len(all_reviews)}건...")
        time.sleep(0.5)

    return all_reviews


def build_version_timeline(raw_reviews: list[dict]) -> list[dict]:
    """
    appVersion별 첫 등장 날짜를 버전 출시일로 추정.
    버전 번호 오름차순 정렬 후 반환.
    """
    if not raw_reviews:
        return []

    records = []
    for r in raw_reviews:
        at = r.get("at")
        ver = (r.get("appVersion") or "").strip()
        if not ver or not isinstance(at, datetime):
            continue
        records.append({"version": ver, "date": at})

    if not records:
        return []

    df = pd.DataFrame(records)
    # 버전별 첫 등장 날짜 (= 출시일 근사)
    first_seen = (
        df.groupby("version")["date"]
        .min()
        .reset_index()
        .rename(columns={"date": "first_seen"})
    )
    first_seen = first_seen.sort_values("first_seen").reset_index(drop=True)

    versions = []
    for _, row in first_seen.iterrows():
        versions.append({
            "version": row["version"],
            "date": row["first_seen"].strftime("%Y-%m-%d"),
            "source": "review_appVersion",
        })

    return versions


def scrape_app(app_meta: dict) -> dict:
    print(f"\n[{app_meta['name']}] 버전 타임라인 추정 중...")
    raw = fetch_reviews_for_versions(app_meta["app_id"])
    print(f"  리뷰 {len(raw)}건 수집")

    versions = build_version_timeline(raw)
    print(f"  고유 버전 {len(versions)}개 탐지")

    return {
        "app_id":        app_meta["app_id"],
        "name":          app_meta["name"],
        "category":      app_meta["category"],
        "scraped_at":    datetime.now().isoformat(),
        "version_count": len(versions),
        "note":          "버전 출시일 = 해당 버전 리뷰 최초 등장일 (근사값)",
        "versions":      versions,
    }


def save_result(app_id: str, data: dict) -> Path:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    out = VERSIONS_DIR / f"{app_id}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  저장: {out}")
    return out


def main():
    print("=" * 60)
    print("버전 히스토리 수집 (리뷰 appVersion 기반)")
    print("=" * 60)

    for app in APP_LIST:
        data = scrape_app(app)
        save_result(app["app_id"], data)
        time.sleep(2)

    print("\n모든 앱 버전 히스토리 수집 완료!")


if __name__ == "__main__":
    main()
