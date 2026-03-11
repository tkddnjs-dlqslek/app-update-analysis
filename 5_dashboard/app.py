"""
Streamlit 대시보드: 앱 업데이트 Before/After 평점 분석
실행: streamlit run 5_dashboard/app.py
"""

import json
from pathlib import Path

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── 경로 설정
BASE_DIR     = Path(__file__).parent.parent
PROCESSED    = BASE_DIR / "data" / "processed"
REVIEWS_DIR  = BASE_DIR / "data" / "raw" / "reviews"

APP_NAMES = {
    "com.sampleapp":          "배달의민족",
    "com.coupang.mobile.eats":"쿠팡이츠",
    "com.coupang.mobile":     "쿠팡",
    "com.dbs.kurly.m2":       "마켓컬리",
    "com.kakaobank.channel":  "카카오뱅크",
    "viva.republica.toss":    "토스",
}
TYPE_LABELS = {"patch": "Patch (버그픽스)", "minor": "Minor (기능추가)", "major": "Major (대형개편)"}
TYPE_COLORS = {"patch": "#3498db", "minor": "#f39c12", "major": "#e74c3c"}


# ── 데이터 로딩
@st.cache_data
def load_analysis():
    df = pd.read_csv(PROCESSED / "all_apps_analysis.csv", parse_dates=["update_date"])
    df["app_name"] = df["app_id"].map(APP_NAMES)
    df["star1_delta"] = df["after_1star_pct"] - df["before_1star_pct"]
    df["update_type_label"] = df["update_type"].map(TYPE_LABELS)
    return df


@st.cache_data
def load_reviews(app_id: str):
    path = REVIEWS_DIR / f"{app_id}.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=["date"])


@st.cache_data
def load_ai_summaries():
    path = PROCESSED / "ai_summaries.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# ── 페이지 설정
st.set_page_config(page_title="앱 업데이트 평점 분석", page_icon="📱", layout="wide")

st.title("📱 앱 업데이트 Before/After 평점 분석")
st.caption("어떤 업데이트가 평점을 올리고, 어떤 업데이트가 평점을 내리는가?")

df = load_analysis()

# ── 사이드바 필터
with st.sidebar:
    st.header("필터")
    selected_apps = st.multiselect(
        "앱 선택", options=list(APP_NAMES.values()), default=list(APP_NAMES.values())
    )
    selected_types = st.multiselect(
        "업데이트 유형", options=list(TYPE_LABELS.values()), default=list(TYPE_LABELS.values())
    )
    delta_range = st.slider("평점 변화 범위", float(df["score_delta"].min()),
                             float(df["score_delta"].max()),
                             (float(df["score_delta"].min()), float(df["score_delta"].max())))

filtered = df[
    (df["app_name"].isin(selected_apps)) &
    (df["update_type_label"].isin(selected_types)) &
    (df["score_delta"].between(*delta_range))
]

# ── KPI 카드
col1, col2, col3, col4 = st.columns(4)
col1.metric("총 분석 업데이트", f"{len(filtered):,}건")
col2.metric("평균 평점 변화", f"{filtered['score_delta'].mean():+.3f}점")
col3.metric("평점 상승 비율", f"{(filtered['score_delta'] > 0).mean()*100:.1f}%")
col4.metric("최대 급락", f"{filtered['score_delta'].min():.3f}점")

st.divider()

# ── 탭 구성
tab1, tab2, tab3, tab4 = st.tabs(["📊 유형별 분석", "📈 시계열", "🔥 히트맵", "🤖 AI 요약"])

# ── TAB 1: 유형별
with tab1:
    c1, c2 = st.columns(2)

    with c1:
        type_stats = filtered.groupby("update_type")["score_delta"].agg(["mean","std","count"])
        type_stats = type_stats.reindex(["patch","minor","major"]).dropna()
        fig = go.Figure()
        for u, row in type_stats.iterrows():
            fig.add_trace(go.Bar(
                x=[TYPE_LABELS[u]], y=[row["mean"]],
                error_y=dict(type="data", array=[row["std"] / np.sqrt(row["count"])]),
                marker_color=TYPE_COLORS[u],
                name=TYPE_LABELS[u],
                text=f"{row['mean']:+.3f} (n={int(row['count'])})",
                textposition="outside",
            ))
        fig.add_hline(y=0, line_dash="dash", line_color="black")
        fig.update_layout(title="업데이트 유형별 평균 평점 변화", showlegend=False,
                          yaxis_title="평균 Δ평점", height=350)
        st.plotly_chart(fig, width="stretch")

    with c2:
        fig2 = px.box(filtered, x="update_type_label", y="score_delta",
                      color="update_type_label",
                      color_discrete_map={v: TYPE_COLORS[k] for k, v in TYPE_LABELS.items()},
                      category_orders={"update_type_label": list(TYPE_LABELS.values())},
                      title="유형별 평점 변화 분포",
                      labels={"update_type_label": "업데이트 유형", "score_delta": "Δ평점"})
        fig2.add_hline(y=0, line_dash="dash", line_color="black")
        fig2.update_layout(showlegend=False, height=350)
        st.plotly_chart(fig2, width="stretch")

    # 앱별 통계 표
    st.subheader("앱별 업데이트 성적표")
    app_tbl = filtered.groupby("app_name").agg(
        분석건수=("score_delta","count"),
        평균평점변화=("score_delta","mean"),
        평점상승비율=("score_delta", lambda x: f"{(x>0).mean()*100:.1f}%"),
        최대급락=("score_delta","min"),
        최대급등=("score_delta","max"),
    ).sort_values("평균평점변화", ascending=False)
    app_tbl["평균평점변화"] = app_tbl["평균평점변화"].map(lambda x: f"{x:+.3f}")
    app_tbl["최대급락"] = app_tbl["최대급락"].map(lambda x: f"{x:.3f}")
    app_tbl["최대급등"] = app_tbl["최대급등"].map(lambda x: f"{x:+.3f}")
    st.dataframe(app_tbl, width="stretch")

# ── TAB 2: 시계열
with tab2:
    app_sel = st.selectbox("앱 선택", selected_apps, key="ts_app")
    sub = filtered[filtered["app_name"] == app_sel].sort_values("update_date")

    fig3 = px.scatter(sub, x="update_date", y="score_delta",
                      color="update_type_label",
                      color_discrete_map={v: TYPE_COLORS[k] for k, v in TYPE_LABELS.items()},
                      hover_data=["version", "before_review_count", "after_review_count"],
                      title=f"{app_sel} — 업데이트별 평점 변화 시계열",
                      labels={"update_date":"날짜", "score_delta":"Δ평점",
                              "update_type_label":"유형"})
    fig3.add_hline(y=0, line_dash="dash", line_color="black")

    # 7일 이동평균 선
    sub_ts = sub.set_index("update_date")["score_delta"].resample("7D").mean().dropna()
    fig3.add_trace(go.Scatter(x=sub_ts.index, y=sub_ts.values,
                              mode="lines", name="7일 이동평균",
                              line=dict(color="black", dash="dot", width=1.5)))
    fig3.update_layout(height=450)
    st.plotly_chart(fig3, width="stretch")

    # 해당 앱 원시 리뷰 샘플
    with st.expander("리뷰 샘플 보기"):
        app_id = {v: k for k, v in APP_NAMES.items()}.get(app_sel)
        if app_id:
            reviews_df = load_reviews(app_id)
            if not reviews_df.empty:
                st.dataframe(reviews_df[["date","score","content","app_version"]].head(20),
                             width="stretch")

# ── TAB 3: 히트맵
with tab3:
    st.subheader("앱 × 업데이트 유형별 평점 변화 히트맵")

    pivot = filtered.pivot_table(
        index="app_name", columns="update_type", values="score_delta", aggfunc="mean"
    ).reindex(columns=["patch","minor","major"]).round(3)
    pivot.columns = ["Patch (버그픽스)", "Minor (기능추가)", "Major (대형개편)"]

    fig4 = px.imshow(pivot, text_auto=".3f", aspect="auto",
                     color_continuous_scale="RdYlGn", color_continuous_midpoint=0,
                     title="평균 Δ평점 (녹색=상승, 빨강=하락)")
    fig4.update_layout(height=350)
    st.plotly_chart(fig4, width="stretch")

    st.subheader("1점 리뷰 비율 변화 히트맵")
    filtered["star1_delta"] = filtered["after_1star_pct"] - filtered["before_1star_pct"]
    pivot2 = filtered.pivot_table(
        index="app_name", columns="update_type", values="star1_delta", aggfunc="mean"
    ).reindex(columns=["patch","minor","major"]).round(2)
    pivot2.columns = ["Patch (버그픽스)", "Minor (기능추가)", "Major (대형개편)"]
    fig5 = px.imshow(pivot2, text_auto=".2f", aspect="auto",
                     color_continuous_scale="RdYlGn_r", color_continuous_midpoint=0,
                     title="Δ 1점 리뷰 비율 (%p) (빨강=1점 증가=악화)")
    fig5.update_layout(height=350)
    st.plotly_chart(fig5, width="stretch")

# ── TAB 4: AI 요약
with tab4:
    summaries = load_ai_summaries()
    if not summaries:
        st.info("AI 요약 데이터가 없습니다. `ANTHROPIC_API_KEY`를 `.env`에 설정 후 `4_ai/review_summarizer.py`를 실행해주세요.")
    else:
        for s in summaries:
            with st.expander(f"**{s['app_name']}** v{s['version']} — Δ{s['score_delta']:.3f}점"):
                st.markdown(f"**한 줄 요약:** {s.get('one_line','')}")
                cols = st.columns(2)
                with cols[0]:
                    st.markdown("**주요 불만 TOP 3**")
                    for i, c in enumerate(s.get("top_complaints", []), 1):
                        st.markdown(f"{i}. {c}")
                with cols[1]:
                    st.markdown("**핵심 키워드**")
                    st.write(" · ".join(s.get("keywords", [])))
