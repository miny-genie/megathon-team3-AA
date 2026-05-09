"""
app.py - MZC Sales Radar (v6 - UI/UX 요구사항 반영)
────────────────────────────────────────────────────
4.1 Landing Page: 미니멀 진입 (페르소나 + 키워드 + 시작)
4.2 Sticky Header: 접이식 키워드 튜닝 바
4.3 Summary Dashboard: 인사이트 요약 + 유형별 기사 + 임팩트 스코어
4.4 Side-by-Side Editor: 참조 원문(좌) + AI 초안(우)
"""
import sys, os
from datetime import datetime
from collections import Counter
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

from config import ROLES, PURPOSES, DEFAULT_KEYWORDS, WINDOW_MAP, NOISE_KEYWORDS
from agents.keyword_planner import recommend_keywords
from agents.collector import collect_articles
from agents.normalizer import normalize_articles
from agents.dedup_vector import dedup_and_vectorize
from agents.insight_analyst import analyze_articles
from agents.persona_briefing import generate_briefing
from services.report_renderer import render_briefing_html
from services.scoring import (
    get_source_weight, build_user_intent_text, build_article_intent_text,
    calculate_role_keyword_match_score, calculate_recency_score,
    calculate_hotness_score, calculate_final_score, build_score_reason,
)
from services.trend_analyzer import extract_trend_keywords, calculate_sentiment_overview, calculate_source_reactions
from services.bedrock_client import get_embedding, invoke_model

st.set_page_config(page_title="MZC Sales Radar", page_icon="📡", layout="wide", initial_sidebar_state="collapsed")

# ─── Custom CSS ───
st.markdown("""<style>
.landing-container { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:70vh; }
.landing-title { font-size:2.5rem; font-weight:700; color:#FF6B00; margin-bottom:0.2em; }
.landing-subtitle { font-size:1.1rem; color:#666; margin-bottom:2em; }
.sticky-header { background:#f8f9fa; border-bottom:1px solid #e0e0e0; padding:12px 20px; border-radius:8px; margin-bottom:1em; }
.impact-score { font-size:2.8rem; font-weight:800; color:#FF4B4B; text-align:center; }
.impact-label { font-size:0.7rem; color:#999; text-align:center; text-transform:uppercase; }
.type-badge { display:inline-block; padding:2px 8px; border-radius:12px; font-size:0.75rem; font-weight:600; margin-right:4px; }
.badge-breaking { background:#fee2e2; color:#dc2626; }
.badge-policy { background:#dbeafe; color:#1d4ed8; }
.badge-csp { background:#f3e8ff; color:#7c3aed; }
.badge-lead { background:#dcfce7; color:#16a34a; }
.badge-trend { background:#fef3c7; color:#d97706; }
.editor-panel { border:1px solid #e0e0e0; border-radius:8px; padding:16px; min-height:400px; background:#fafafa; }
.editor-panel-right { border:1px solid #4caf50; border-radius:8px; padding:16px; min-height:400px; background:#f0fdf4; }
</style>""", unsafe_allow_html=True)

# ─── Session State ───
if "phase" not in st.session_state:
    st.session_state["phase"] = "landing"  # landing → dashboard
if "keyword_pool" not in st.session_state:
    st.session_state["keyword_pool"] = list(DEFAULT_KEYWORDS)
if "search_keywords" not in st.session_state:
    st.session_state["search_keywords"] = []
if "header_expanded" not in st.session_state:
    st.session_state["header_expanded"] = True


# ═══════════════════════════════════════════════════
# 4.1 Landing Page
# ═══════════════════════════════════════════════════
if st.session_state["phase"] == "landing":
    st.markdown("<div class='landing-container'>", unsafe_allow_html=True)
    st.markdown("<div class='landing-title'>📡 MZC Sales Radar</div>", unsafe_allow_html=True)
    st.markdown("<div class='landing-subtitle'>CSA: 비즈니스 인텔리전스 에이전트 — 뉴스에서 영업 기회를 발견합니다</div>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        # 페르소나 선택
        persona = st.selectbox(
            "👤 페르소나 선택",
            list(ROLES.keys()),
            index=0,
            help="자신의 직군을 선택하세요",
        )

        # 최소 키워드 입력
        keyword_input = st.text_input(
            "🔍 키워드 입력",
            placeholder="산업군, 고객사명 또는 경쟁사명 (예: 금융 망분리, 삼성전자)",
            help="쉼표로 구분하여 여러 키워드 입력 가능",
        )

        # 조회 기간
        period = st.radio("📅 조회 기간", list(WINDOW_MAP.keys()), horizontal=True, index=0)

        st.markdown("")
        if st.button("🚀 시작하기", type="primary", use_container_width=True):
            if not ROLES[persona]["supported"]:
                st.error("MVP에서는 영업/프리세일즈만 지원합니다.")
            else:
                # 키워드 파싱
                kws = [k.strip() for k in keyword_input.split(",") if k.strip()] if keyword_input else DEFAULT_KEYWORDS[:4]
                st.session_state["selected_role"] = persona
                st.session_state["role_key"] = ROLES[persona]["target_role"]
                st.session_state["search_keywords"] = kws
                st.session_state["keyword_pool"] = list(set(DEFAULT_KEYWORDS + kws))
                st.session_state["time_window"] = WINDOW_MAP[period]
                st.session_state["phase"] = "loading"
                st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


# ═══════════════════════════════════════════════════
# Loading Phase: 백그라운드 수집 + 분석
# ═══════════════════════════════════════════════════
if st.session_state["phase"] == "loading":
    st.markdown("## ⏳ AI 에이전트가 뉴스를 탐색하고 있습니다...")
    progress = st.progress(0)

    kws = st.session_state["search_keywords"]
    window = st.session_state["time_window"]
    role_key = st.session_state["role_key"]

    # Step 1: 수집
    progress.progress(0.1, "📡 5개 언론사에서 뉴스 수집 중...")
    collect_result = collect_articles(kws, window)
    norm_result = normalize_articles(collect_result["raw_articles"])
    articles = norm_result["normalized_articles"]
    progress.progress(0.3, f"✅ {len(articles)}건 수집 완료")

    # Step 2: 중복 제거
    progress.progress(0.4, "🔄 중복/노이즈 제거 중...")
    dedup_result = dedup_and_vectorize(articles)
    filtered = dedup_result["filtered_articles"]
    progress.progress(0.5, f"✅ {len(filtered)}건 유효")

    # Step 3: 분석
    progress.progress(0.6, "🧠 Bedrock 기사 분석 중...")
    analyzed = analyze_articles(filtered, st.session_state["selected_role"], "custom_search")
    progress.progress(0.7, f"✅ {len(analyzed)}건 분석 완료")

    # Step 4: 스코어링
    progress.progress(0.8, "📊 스코어링 중...")
    user_intent = build_user_intent_text(role_key, "custom_search", kws, [])
    try:
        user_vector = np.array(get_embedding(user_intent), dtype=np.float32)
    except Exception:
        user_vector = np.zeros(1024, dtype=np.float32)

    opp_counts = Counter(a.get("opportunity_type", "other") for a in analyzed)
    max_cluster = max(opp_counts.values()) if opp_counts else 1

    for art in analyzed:
        # 이유: dedup 단계에서 이미 생성된 embedding 재사용 → Bedrock 호출 0회
        if "embedding" in art and art["embedding"]:
            art_vector = np.array(art["embedding"], dtype=np.float32)
        else:
            # fallback: embedding 없는 기사만 새로 호출
            try:
                art_vector = np.array(get_embedding(build_article_intent_text(art)), dtype=np.float32)
            except Exception:
                art_vector = np.zeros_like(user_vector)

        rk_score = calculate_role_keyword_match_score(user_vector, art_vector)
        art["role_keyword_match_score"] = rk_score
        art["recency_score"] = calculate_recency_score(art.get("published_at", ""))
        art["hotness_score"] = calculate_hotness_score(opp_counts.get(art.get("opportunity_type","other"),1), max_cluster)
        art["source_weight"] = get_source_weight(art.get("source_id",""), role_key, art.get("section",""), "custom_search", art.get("opportunity_type",""))
        art["llm_importance"] = art.get("importance", 5)
        noise_p = 0.7 if any(nk in art.get("title","").lower() for nk in NOISE_KEYWORDS) else 1.0
        final = calculate_final_score(art, art["source_weight"], rk_score, art["recency_score"], art["hotness_score"], noise_p)
        art["final_score_100"] = final
        art["score_reason"] = build_score_reason(art, final, art["source_weight"], rk_score)

    analyzed.sort(key=lambda x: x.get("final_score_100", 0), reverse=True)

    # Step 5: 트렌드/여론
    progress.progress(0.9, "📈 트렌드/여론 분석 중...")
    trends = extract_trend_keywords(analyzed)
    sentiment_ov = calculate_sentiment_overview(analyzed)
    source_rx = calculate_source_reactions(analyzed)

    # 저장
    st.session_state["articles"] = analyzed
    st.session_state["trends"] = trends
    st.session_state["sentiment_overview"] = sentiment_ov
    st.session_state["source_reactions"] = source_rx
    st.session_state["collect_result"] = collect_result
    st.session_state["phase"] = "dashboard"
    progress.progress(1.0, "✅ 완료!")
    st.rerun()


# ═══════════════════════════════════════════════════
# 4.2~4.4 Dashboard Phase
# ═══════════════════════════════════════════════════
if st.session_state["phase"] == "dashboard":
    articles = st.session_state["articles"]
    trends = st.session_state["trends"]
    sentiment_ov = st.session_state["sentiment_overview"]
    source_rx = st.session_state["source_reactions"]

    # ─── 4.2 Sticky Header (접이식) ───
    with st.container():
        hdr_col1, hdr_col2 = st.columns([9, 1])
        with hdr_col1:
            role_display = st.session_state["selected_role"]
            kw_display = ", ".join(st.session_state["search_keywords"][:5])
            if st.session_state["header_expanded"]:
                st.markdown(f"**👤 {role_display}** | 🔍 키워드: {kw_display} | 📰 {len(articles)}건 분석됨")
            else:
                st.caption(f"👤 {role_display} | 🔍 {kw_display} | 📰 {len(articles)}건")
        with hdr_col2:
            if st.button("📌" if st.session_state["header_expanded"] else "📎"):
                st.session_state["header_expanded"] = not st.session_state["header_expanded"]
                st.rerun()

        if st.session_state["header_expanded"]:
            # 키워드 튜닝 인터페이스
            st.markdown("---")
            tune_col1, tune_col2 = st.columns([1, 3])
            with tune_col1:
                if st.button("🤖 AI 키워드 추천"):
                    with st.spinner("추천 중..."):
                        r = recommend_keywords(st.session_state["search_keywords"][:5], st.session_state["selected_role"], "custom_search")
                        for kw in r.get("recommended_keywords", []):
                            if kw not in st.session_state["keyword_pool"]:
                                st.session_state["keyword_pool"].append(kw)
                        st.rerun()
            with tune_col2:
                # Keyword Chips (multiselect로 구현)
                active_kws = st.multiselect(
                    "활성 키워드 (추가/제거 가능)",
                    options=st.session_state["keyword_pool"],
                    default=st.session_state["search_keywords"],
                    label_visibility="collapsed",
                )
                if set(active_kws) != set(st.session_state["search_keywords"]):
                    st.session_state["search_keywords"] = active_kws

            # 재검색 버튼
            if st.button("🔄 키워드 변경 후 재분석", use_container_width=True):
                st.session_state["phase"] = "loading"
                st.rerun()
            st.markdown("---")

    # ─── 4.3 Summary Dashboard ───
    # A. 인사이트 요약 문장
    st.subheader("💡 인사이트 요약")
    if articles:
        top = articles[0]
        sentiment_label = sentiment_ov.get("label", "중립/혼재") if sentiment_ov else "분석 중"
        st.info(f"**Context:** 현재 시장은 '{sentiment_label}' 상태이며, 상위 기사는 '{top.get('opportunity_type','market_trend')}' 유형입니다. "
                f"**Action:** {top.get('suggested_action', '주요 기사를 확인하고 고객 접점을 준비하세요.')}")

    # B. 유형별 기사 목록 (Top 5 with Impact Score)
    st.subheader("📰 Priority News")

    for rank, art in enumerate(articles[:5], 1):
        left, right = st.columns([8, 2])
        with left:
            # Type badge
            opp = art.get("opportunity_type", "other")
            badge_map = {
                "sales_opportunity": ("SALES LEAD", "badge-lead"),
                "lead_generation": ("SALES LEAD", "badge-lead"),
                "customer_signal": ("SALES LEAD", "badge-lead"),
                "proposal_evidence": ("POLICY ALERT", "badge-policy"),
                "competitive_intelligence": ("CSP UPDATE", "badge-csp"),
                "competitor_signal": ("CSP UPDATE", "badge-csp"),
                "market_trend": ("TREND", "badge-trend"),
                "security_risk": ("BREAKING NEWS", "badge-breaking"),
            }
            badge_text, badge_class = badge_map.get(opp, ("NEWS", "badge-trend"))
            st.markdown(f"<span class='type-badge {badge_class}'>{badge_text}</span>", unsafe_allow_html=True)

            st.markdown(f"**{art.get('title', '')}**")
            st.caption(f"{art.get('source_name','')} | {art.get('published_at','')[:10]}")

            with st.expander("💡 인사이트 & 액션"):
                st.write(f"**요약:** {art.get('summary_ko', art.get('snippet','')[:200])}")
                st.write(f"**Why it matters:** {art.get('why_it_matters','')}")
                st.markdown(f"🎯 **Recommended Action:** {art.get('suggested_action','')}")
                st.caption(f"Score: {art.get('score_reason','')}")
                st.link_button("원문 보기", art.get("url", "#"))

        with right:
            st.markdown(f"<div class='impact-label'>IMPACT SCORE</div><div class='impact-score'>{art.get('final_score_100', 0)}</div>", unsafe_allow_html=True)

        st.divider()

    # ─── 대시보드 차트 ───
    dash_tab1, dash_tab2, dash_tab3, dash_tab4 = st.tabs(["📈 트렌드", "💭 여론", "🔥 언론사 반응", "📊 통계"])

    with dash_tab1:
        if trends:
            tdf = pd.DataFrame(trends[:10])
            if "trend_keyword" in tdf.columns:
                fig = px.bar(tdf, x="trend_keyword", y="trend_score", title="Top 10 트렌드 키워드", color="trend_score", color_continuous_scale="Oranges")
                st.plotly_chart(fig, use_container_width=True)

    with dash_tab2:
        if sentiment_ov:
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Sentiment Index", f"{sentiment_ov.get('sentiment_index',0):.2f}")
            s2.metric("긍정", sentiment_ov.get("positive_count", 0))
            s3.metric("중립", sentiment_ov.get("neutral_count", 0))
            s4.metric("부정", sentiment_ov.get("negative_count", 0))
            st.caption(f"전체 여론: **{sentiment_ov.get('label','')}**")
            pie_df = pd.DataFrame({"감성": ["긍정","중립","부정"], "수": [sentiment_ov.get("positive_count",0), sentiment_ov.get("neutral_count",0), sentiment_ov.get("negative_count",0)]})
            fig = px.pie(pie_df, names="감성", values="수", color="감성", color_discrete_map={"긍정":"#22c55e","중립":"#9ca3af","부정":"#ef4444"})
            st.plotly_chart(fig, use_container_width=True)

    with dash_tab3:
        if source_rx:
            rx_df = pd.DataFrame(source_rx)
            if "source_name" in rx_df.columns:
                color_map = {"HOT": "#ef4444", "HOT RISK": "#7f1d1d", "WARM": "#f97316", "COLD": "#3b82f6"}
                fig = px.bar(rx_df, x="source_name", y="source_reaction_score", color="reaction_label", title="언론사별 반응", color_discrete_map=color_map)
                st.plotly_chart(fig, use_container_width=True)

    with dash_tab4:
        if articles:
            df = pd.DataFrame(articles)
            c1, c2 = st.columns(2)
            with c1:
                if "source_name" in df.columns:
                    fig = px.bar(df["source_name"].value_counts().reset_index(), x="source_name", y="count", title="언론사별 기사 수")
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                if "sentiment" in df.columns:
                    fig = px.pie(df["sentiment"].value_counts().reset_index(), names="sentiment", values="count", title="감성 분포")
                    st.plotly_chart(fig, use_container_width=True)

    # ─── 4.4 Side-by-Side Editor ───
    st.markdown("---")
    st.subheader("✍️ AI 초안 에디터")
    st.caption("좌측: 참조 뉴스 원문 | 우측: AI가 생성한 비즈니스 초안 (키워드 변경 시 자동 재작성)")

    # 목적 선택
    purpose_for_draft = st.radio("초안 유형", list(PURPOSES.keys()), horizontal=True, label_visibility="collapsed", index=0)
    purpose_id = PURPOSES[purpose_for_draft]["id"]

    editor_left, editor_right = st.columns(2)

    with editor_left:
        st.markdown("<div class='editor-panel'>", unsafe_allow_html=True)
        st.markdown("**📄 참조 뉴스 원문**")
        if articles:
            # 상위 3개 기사 원문 표시
            for a in articles[:3]:
                st.markdown(f"**[{a.get('source_name','')}]** {a.get('title','')}")
                st.write(a.get("snippet", "")[:300])
                st.markdown("---")
        st.markdown("</div>", unsafe_allow_html=True)

    with editor_right:
        st.markdown("<div class='editor-panel-right'>", unsafe_allow_html=True)
        st.markdown("**✨ AI 생성 초안 (V+)**")

        if st.button("📝 초안 생성", type="primary", use_container_width=True):
            with st.spinner("Bedrock으로 초안 작성 중..."):
                briefing_content = generate_briefing(st.session_state["selected_role"], purpose_id, articles[:10])
                stats = {"total_collected": len(articles), "after_dedup": len(articles), "analyzed": len(articles), "high_importance": sum(1 for a in articles if a.get("importance",0)>=8), "avg_purpose_fit": 0.7}
                briefing_html = render_briefing_html(st.session_state["selected_role"], purpose_for_draft, briefing_content, articles[:10], stats)
                st.session_state["briefing_html"] = briefing_html
                st.session_state["draft_content"] = briefing_content
                st.rerun()

        if "draft_content" in st.session_state:
            st.markdown(st.session_state["draft_content"], unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # ─── Export ───
    if "briefing_html" in st.session_state:
        st.markdown("---")
        st.subheader("📥 내보내기")
        ec1, ec2, ec3, ec4 = st.columns(4)
        bhtml = st.session_state["briefing_html"]
        ec1.download_button("📄 HTML", bhtml, "briefing.html", "text/html", use_container_width=True)
        ec2.download_button("📝 DOCX", f"<html><head><meta charset='utf-8'></head><body>{bhtml}</body></html>".encode(), "briefing.doc", "application/msword", use_container_width=True)
        ec3.download_button("📋 PDF용", bhtml.replace("</head>","<script>window.onload=function(){window.print();}</script></head>"), "print.html", "text/html", use_container_width=True)
        from bs4 import BeautifulSoup
        ec4.download_button("📒 Notion", BeautifulSoup(bhtml,"html.parser").get_text("\n\n"), "briefing.md", "text/markdown", use_container_width=True)

    # ─── 처음으로 돌아가기 ───
    st.markdown("---")
    if st.button("🏠 처음으로 돌아가기"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
