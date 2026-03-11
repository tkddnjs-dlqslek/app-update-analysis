"""
전처리: 버전-리뷰 결합 + Before/After 구간 분리
- 입력: data/raw/versions/*.json + data/raw/reviews/*.csv
- 출력: data/processed/{app_id}_analysis.csv
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

VERSIONS_DIR = Path(__file__).parent.parent / "data" / "raw" / "versions"
REVIEWS_DIR  = Path(__file__).parent.parent / "data" / "raw" / "reviews"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

# 업데이트 전/후 각 분석 기간 (일)
WINDOW_DAYS = 30


def load_app_ids() -> list[str]:
    return [p.stem for p in REVIEWS_DIR.glob("*.csv")]


def load_versions(app_id: str) -> pd.DataFrame:
    path = VERSIONS_DIR / f"{app_id}.json"
    if not path.exists():
        return pd.DataFrame(columns=["version", "date"])
    data = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(data.get("versions", []))
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def load_reviews(app_id: str) -> pd.DataFrame:
    path = REVIEWS_DIR / f"{app_id}.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["date"])
    return df


def classify_update_type(version: str, prev_version: str) -> str:
    """
    버전 번호 변화로 업데이트 유형 추정.
    major.minor.patch 규칙 기반.
    """
    def parse(v: str):
        parts = str(v).split(".")
        try:
            return [int(p) for p in parts[:3]]
        except ValueError:
            return [0, 0, 0]

    cur  = parse(version)
    prev = parse(prev_version)

    if len(cur) < 3 or len(prev) < 3:
        return "unknown"

    if cur[0] != prev[0]:
        return "major"      # 대형 업데이트 (UI 개편 가능성)
    elif cur[1] != prev[1]:
        return "minor"      # 기능 추가
    else:
        return "patch"      # 버그픽스


def build_update_windows(versions: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    """
    각 업데이트를 기준으로 Before/After 리뷰 윈도우를 생성.
    Returns: 업데이트 × 구간별 평점 통계 DataFrame
    """
    records = []

    for i, row in versions.iterrows():
        update_date = row["date"]
        version     = row["version"]
        prev_version = versions.iloc[i - 1]["version"] if i > 0 else version

        before_start = update_date - pd.Timedelta(days=WINDOW_DAYS)
        after_end    = update_date + pd.Timedelta(days=WINDOW_DAYS)

        before = reviews[
            (reviews["date"] >= before_start) & (reviews["date"] < update_date)
        ]
        after = reviews[
            (reviews["date"] >= update_date) & (reviews["date"] <= after_end)
        ]

        if len(before) < 5 or len(after) < 5:
            # 데이터 부족 시 스킵
            continue

        update_type = classify_update_type(version, prev_version)

        records.append({
            "version":            version,
            "prev_version":       prev_version,
            "update_type":        update_type,
            "update_date":        update_date.strftime("%Y-%m-%d"),
            "before_avg_score":   round(before["score"].mean(), 3),
            "after_avg_score":    round(after["score"].mean(), 3),
            "score_delta":        round(after["score"].mean() - before["score"].mean(), 3),
            "before_review_count": len(before),
            "after_review_count":  len(after),
            "before_1star_pct":   round((before["score"] == 1).mean() * 100, 1),
            "after_1star_pct":    round((after["score"] == 1).mean() * 100, 1),
            "before_5star_pct":   round((before["score"] == 5).mean() * 100, 1),
            "after_5star_pct":    round((after["score"] == 5).mean() * 100, 1),
        })

    return pd.DataFrame(records)


def process_app(app_id: str) -> pd.DataFrame | None:
    print(f"\n[{app_id}] 전처리 시작")

    versions = load_versions(app_id)
    reviews  = load_reviews(app_id)

    if versions.empty:
        print("  버전 히스토리 없음 — 스킵")
        return None
    if reviews.empty:
        print("  리뷰 데이터 없음 — 스킵")
        return None

    print(f"  버전 {len(versions)}개 / 리뷰 {len(reviews)}건")

    result = build_update_windows(versions, reviews)
    result.insert(0, "app_id", app_id)

    print(f"  분석 가능한 업데이트: {len(result)}건")
    return result


def main():
    print("=" * 60)
    print("전처리: 버전-리뷰 결합 + Before/After 구간 분리")
    print("=" * 60)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    all_dfs = []

    for app_id in load_app_ids():
        df = process_app(app_id)
        if df is not None and not df.empty:
            out = PROCESSED_DIR / f"{app_id}_analysis.csv"
            df.to_csv(out, index=False, encoding="utf-8-sig")
            print(f"  저장: {out}")
            all_dfs.append(df)

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        out = PROCESSED_DIR / "all_apps_analysis.csv"
        combined.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n전체 통합 저장: {out} ({len(combined)}행)")


if __name__ == "__main__":
    main()
