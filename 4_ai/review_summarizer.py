"""
Claude API 부정 리뷰 자동 요약
- 업데이트 후 평점이 급락한 버전의 1점 리뷰를 모아 Claude가 요약
- 결과: data/processed/ai_summaries.json
"""

import json
import os
from pathlib import Path

import anthropic
import pandas as pd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
REVIEWS_DIR   = Path(__file__).parent.parent / "data" / "raw" / "reviews"

APP_NAMES = {
    "com.sampleapp":          "배달의민족",
    "com.coupang.mobile.eats":"쿠팡이츠",
    "com.coupang.mobile":     "쿠팡",
    "com.dbs.kurly.m2":       "마켓컬리",
    "com.kakaobank.channel":  "카카오뱅크",
    "viva.republica.toss":    "토스",
}

SUMMARY_PROMPT = """\
다음은 '{app_name}' 앱의 {version} 버전 업데이트 이후 30일 내에 작성된 1점(최하점) 리뷰들입니다.

이 리뷰들을 분석해서 아래 형식으로 요약해주세요:

1. **주요 불만 3가지** (가장 많이 언급된 순)
2. **핵심 키워드 5개**
3. **한 줄 요약** (개발팀이 즉시 행동할 수 있도록)

--- 리뷰 시작 ---
{reviews}
--- 리뷰 끝 ---

JSON 형식으로만 응답하세요:
{{
  "top_complaints": ["불만1", "불만2", "불만3"],
  "keywords": ["키1", "키2", "키3", "키4", "키5"],
  "one_line": "한 줄 요약"
}}"""


def get_worst_updates(top_n: int = 10) -> list[dict]:
    """평점 급락 업데이트 목록 (score_delta 기준 하위 N개)."""
    df = pd.read_csv(PROCESSED_DIR / "all_apps_analysis.csv")
    worst = df.nsmallest(top_n, "score_delta")[
        ["app_id", "version", "update_date", "score_delta", "after_1star_pct"]
    ]
    return worst.to_dict("records")


def get_negative_reviews(app_id: str, version: str, update_date: str,
                          max_reviews: int = 30) -> list[str]:
    """특정 버전 업데이트 후 1점 리뷰 수집."""
    csv_path = REVIEWS_DIR / f"{app_id}.csv"
    if not csv_path.exists():
        return []

    df = pd.read_csv(csv_path, parse_dates=["date"])
    update_dt = pd.to_datetime(update_date)
    after_window = update_dt + pd.Timedelta(days=30)

    mask = (
        (df["date"] >= update_dt) &
        (df["date"] <= after_window) &
        (df["score"] == 1) &
        (df["content"].notna()) &
        (df["content"].str.len() > 10)
    )
    reviews = df[mask]["content"].dropna().tolist()[:max_reviews]
    return reviews


def summarize_with_claude(app_name: str, version: str, reviews: list[str]) -> dict:
    """Claude API로 부정 리뷰 요약."""
    reviews_text = "\n".join(f"- {r}" for r in reviews)
    prompt = SUMMARY_PROMPT.format(
        app_name=app_name,
        version=version,
        reviews=reviews_text,
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # JSON 파싱
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    return json.loads(raw[start:end])


def main():
    print("=" * 60)
    print("Claude AI 부정 리뷰 자동 요약")
    print("=" * 60)

    worst_updates = get_worst_updates(top_n=10)
    results = []

    for item in worst_updates:
        app_id      = item["app_id"]
        version     = item["version"]
        update_date = item["update_date"]
        app_name    = APP_NAMES.get(app_id, app_id)

        print(f"\n[{app_name}] v{version} (score_delta={item['score_delta']:.3f})")

        reviews = get_negative_reviews(app_id, version, update_date)
        if len(reviews) < 3:
            print(f"  리뷰 부족 ({len(reviews)}건) — 스킵")
            continue

        print(f"  1점 리뷰 {len(reviews)}건 → Claude 요약 중...")
        try:
            summary = summarize_with_claude(app_name, version, reviews)
            print(f"  한 줄 요약: {summary.get('one_line', '')}")

            results.append({
                "app_id":      app_id,
                "app_name":    app_name,
                "version":     version,
                "update_date": update_date,
                "score_delta": item["score_delta"],
                "review_count": len(reviews),
                **summary,
            })
        except Exception as e:
            print(f"  Claude 오류: {e}")

    out = PROCESSED_DIR / "ai_summaries.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장 완료: {out} ({len(results)}건)")


if __name__ == "__main__":
    main()
