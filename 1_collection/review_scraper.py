"""
Google Play 리뷰/평점 수집기 (google-play-scraper)
- 앱별 최근 리뷰를 수집 + 버전 히스토리와 결합 가능한 형태로 저장
- 결과: data/raw/reviews/{app_id}.csv
"""

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from google_play_scraper import Sort, reviews, app as gp_app

# ───────────────────────────────────────────
# 분석 대상 앱 목록 (apkmirror_scraper.py와 동일)
# ───────────────────────────────────────────
APP_LIST = [
    {"app_id": "com.sampleapp",          "name": "배달의민족", "category": "배달"},
    {"app_id": "com.coupang.mobile.eats", "name": "쿠팡이츠",   "category": "배달"},
    {"app_id": "com.coupang.mobile",     "name": "쿠팡",       "category": "커머스"},
    {"app_id": "com.dbs.kurly.m2",       "name": "마켓컬리",   "category": "커머스"},
    {"app_id": "com.kakaobank.channel",  "name": "카카오뱅크", "category": "금융"},
    {"app_id": "viva.republica.toss",    "name": "토스",       "category": "금융"},
]

# 리뷰 수집 설정
REVIEW_COUNT = 5000   # 앱당 최대 수집 리뷰 수 (충분한 Before/After 분석용)
LANG = "ko"
COUNTRY = "kr"

REVIEWS_DIR = Path(__file__).parent.parent / "data" / "raw" / "reviews"
VERSIONS_DIR = Path(__file__).parent.parent / "data" / "raw" / "versions"


def fetch_app_info(app_id: str) -> dict:
    """앱 기본 정보 (현재 평점, 다운로드 수 등) 수집."""
    try:
        info = gp_app(app_id, lang=LANG, country=COUNTRY)
        return {
            "title": info.get("title"),
            "score": info.get("score"),
            "ratings": info.get("ratings"),
            "installs": info.get("installs"),
            "updated": info.get("updated"),
        }
    except Exception as e:
        print(f"  앱 정보 수집 실패: {e}")
        return {}


def fetch_reviews_batch(app_id: str, count: int = REVIEW_COUNT) -> list[dict]:
    """
    google-play-scraper로 리뷰 수집.
    NEWEST 정렬로 최신 리뷰부터 가져옴.
    continuation_token으로 페이지네이션 처리.
    """
    all_reviews = []
    token = None
    batch_size = 200  # 1회 요청당 최대 200건

    print(f"  목표: {count}건")
    while len(all_reviews) < count:
        remaining = count - len(all_reviews)
        fetch_count = min(batch_size, remaining)

        try:
            result, token = reviews(
                app_id,
                lang=LANG,
                country=COUNTRY,
                sort=Sort.NEWEST,
                count=fetch_count,
                continuation_token=token,
            )
        except Exception as e:
            print(f"  리뷰 수집 오류: {e}")
            break

        if not result:
            break

        all_reviews.extend(result)
        print(f"  {len(all_reviews)}건 수집...")

        if token is None:
            break  # 더 이상 데이터 없음

        time.sleep(1.0)  # 요청 간 딜레이

    return all_reviews


def normalize_reviews(raw_reviews: list[dict], app_info: dict, app_meta: dict) -> pd.DataFrame:
    """원시 리뷰 데이터를 분석용 DataFrame으로 정규화."""
    records = []
    for r in raw_reviews:
        at = r.get("at")
        records.append({
            "app_id": app_meta["app_id"],
            "app_name": app_meta["name"],
            "category": app_meta["category"],
            "review_id": r.get("reviewId", ""),
            "date": at.strftime("%Y-%m-%d") if isinstance(at, datetime) else str(at)[:10],
            "datetime": at.isoformat() if isinstance(at, datetime) else str(at),
            "score": r.get("score", 0),
            "thumbs_up": r.get("thumbsUpCount", 0),
            "username": r.get("userName", ""),
            "content": r.get("content", ""),
            "reply_content": r.get("replyContent", ""),
            "app_version": r.get("appVersion", ""),
        })
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.sort_values("datetime", ascending=False).reset_index(drop=True)
    return df


def load_versions(app_id: str) -> list[dict]:
    """APKMirror 수집 결과에서 버전 날짜 목록 로드."""
    path = VERSIONS_DIR / f"{app_id}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("versions", [])


def add_version_context(df: pd.DataFrame, versions: list[dict]) -> pd.DataFrame:
    """
    각 리뷰에 '직전 업데이트 버전'과 '업데이트 후 경과일' 컬럼 추가.
    versions: [{"version": "x.y.z", "date": "YYYY-MM-DD"}, ...]
    """
    if df.empty or not versions:
        df["nearest_version"] = None
        df["days_after_update"] = None
        return df

    # 날짜 기준 정렬 (최신 → 과거)
    ver_df = pd.DataFrame(versions).dropna(subset=["date"])
    ver_df = ver_df[ver_df["date"] != ""]
    ver_df["date"] = pd.to_datetime(ver_df["date"], errors="coerce")
    ver_df = ver_df.dropna(subset=["date"]).sort_values("date", ascending=False)

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    nearest_versions = []
    days_after = []

    for review_date in df["date"]:
        if pd.isna(review_date):
            nearest_versions.append(None)
            days_after.append(None)
            continue
        # 리뷰 날짜 이전의 가장 최근 업데이트 찾기
        prior = ver_df[ver_df["date"] <= review_date]
        if prior.empty:
            nearest_versions.append(None)
            days_after.append(None)
        else:
            row = prior.iloc[0]
            nearest_versions.append(row["version"])
            days_after.append((review_date - row["date"]).days)

    df["nearest_version"] = nearest_versions
    df["days_after_update"] = days_after
    return df


def scrape_app(app_meta: dict) -> pd.DataFrame:
    """단일 앱 전체 파이프라인: 앱 정보 + 리뷰 + 버전 컨텍스트."""
    print(f"\n[{app_meta['name']}] 수집 시작")

    # 1. 앱 기본 정보
    app_info = fetch_app_info(app_meta["app_id"])
    print(f"  현재 평점: {app_info.get('score', 'N/A')} | 설치 수: {app_info.get('installs', 'N/A')}")

    # 2. 리뷰 수집
    raw = fetch_reviews_batch(app_meta["app_id"])
    print(f"  총 {len(raw)}건 수집 완료")

    # 3. 정규화
    df = normalize_reviews(raw, app_info, app_meta)

    # 4. 버전 컨텍스트 추가
    versions = load_versions(app_meta["app_id"])
    if versions:
        df = add_version_context(df, versions)
        print(f"  버전 컨텍스트 매핑 완료 ({len(versions)}개 버전)")
    else:
        print("  버전 히스토리 없음 (apkmirror_scraper.py 먼저 실행 권장)")

    return df


def save_reviews(app_id: str, df: pd.DataFrame) -> Path:
    """CSV 저장."""
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    out = REVIEWS_DIR / f"{app_id}.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"  저장: {out} ({len(df)}행)")
    return out


def print_summary(df: pd.DataFrame):
    """수집 결과 간단 통계 출력."""
    if df.empty:
        print("  데이터 없음")
        return
    print(f"  날짜 범위: {df['date'].min()} ~ {df['date'].max()}")
    print(f"  평균 평점: {df['score'].mean():.2f}")
    print(f"  평점 분포:\n{df['score'].value_counts().sort_index().to_string()}")


def main():
    print("=" * 60)
    print("Google Play 리뷰 수집기")
    print("=" * 60)

    for app_meta in APP_LIST:
        df = scrape_app(app_meta)
        save_reviews(app_meta["app_id"], df)
        print_summary(df)
        time.sleep(3)

    print("\n모든 앱 리뷰 수집 완료!")


if __name__ == "__main__":
    main()
