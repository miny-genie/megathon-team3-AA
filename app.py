"""
app.py - MZC Sales Radar (v5 - 인터페이스 정합성 수정)
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
    ROLE_INTENT_PROFILES,
)
from services.trend_analyzer import extract_trend_keywords, calculate_sentiment_overview, calculate_source_reactions
from services.bedrock_client import get_embedding

st.set_page_config(page_title="MZC Sales Radar", page_icon="📡", layout="wide")

# ─── Session State ───
if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False
if "keyword_pool" not in st.session_state:
    st.session_state["keyword_pool"] = list(DEFAULT_KEYWORDS)
if "search_keywords" not in st.session_state:
    st.session_state["search_keywords"] = list(DEFAULT_KEYWORDS[:4])

# ─── Header ───
h1, h2 = st.columns([8, 2])
with h1:
    st.title("📡 MZC Sales Radar")
    st.caption("AWS Bedrock + AgentCore 기반 Multi-Agent 뉴스 인텔리전스")
with h2:
    dark = st.toggle("🌙 다크모드", value=st.session_state["dark_mode"])
    if dark != st.session_state["dark_mode"]:
        st.session_state["dark_mode"] = dark
        st.rerun()

# ─── Export (결과 있을 때) ───
if "briefing_html" in st.session_state:
    ec1, ec2, ec3, ec4 = st.columns(4)
    bhtml = st.session_state["briefing_html"]
    ec1.download_button("📄 HTML", bhtml, "briefing.html", "text/html", use_container_width=True)
    ec2.download_button("📝 DOCX", f"<html><head><meta charset='utf-8'></head><body>{bhtml}</body></html>".encode(), "briefing.doc", "application/msword", use_container_width=True)
    ec3.download_button("📋 PDF용", bhtml.replace("</head>", "<script>window.onload=function(){window.print();}</script></head>"), "briefing_print.html", "text/html", use_container_width=True)
    from bs4 import BeautifulSoup
    ec4.download_button("📒 Notion", BeautifulSoup(bhtml, "html.parser").get_text("\n\n"), "briefing.md", "text/markdown", use_container_width=True)
    st.divider()

# ─── Sidebar ───
with st.sidebar:
    st.header("⚙️ 설정")

    # 1. 직군
    st.subheader("1️⃣ 직군")
    selected_role = st.radio("직군", list(ROLES.keys()), horizontal=True, label_visibility="collapsed", index=0)
    if not ROLES[selected_role]["supported"]:
        st.warning("⚠️ MVP에서는 영업/프리세일즈만 지원합니다.")
        st.stop()
    role_key = ROLES[selected_role]["target_role"]  # "sales" or "presales"

    # 2. 조회 기간
    st.subheader("2️⃣ 조회 기간")
    time_window = st.radio("기간", list(WINDOW_MAP.keys()), horizontal=True, label_visibility="collapsed", index=0)

    # 3. 키워드
    st.subheader("3️⃣ 키워드")
    if st.button("🤖 AI 키워드 추천", use_container_width=True):
        with st.spinner("추천 중..."):
            r = recommend_keywords(st.session_state["search_keywords"][:5], selected_role, "custom_search")
            for kw in r.get("recommended_keywords", []):
                if kw not in st.session_state["keyword_pool"]:
                    st.session_state["keyword_pool"].append(kw)
            st.rerun()

    new_pool_kw = st.text_input("키워드 풀에 추가", placeholder="Enter로 추가", label_visibility="collapsed", key="pool_input")
    if new_pool_kw and new_pool_kw.strip() not in st.session_state["keyword_pool"]:
        st.session_state["keyword_pool"].append(new_pool_kw.strip())
        st.rerun()

    st.caption("📦 키워드 풀 → 선택하면 검색으로 이동")
    pool_avail = [k for k in st.session_state["keyword_pool"] if k not in st.session_state["search_keywords"]]
    add_to_search = st.multiselect("풀에서 추가", pool_avail, default=[], label_visibility="collapsed", key="pool_sel")
    if add_to_search:
        for k in add_to_search:
            st.session_state["search_keywords"].append(k)
        st.rerun()

    st.caption("🔍 실제 검색 키워드")
    new_search_kw = st.text_input("검색 키워드 직접 추가", placeholder="Enter로 추가", label_visibility="collapsed", key="search_input")
    if new_search_kw and new_search_kw.strip() not in st.session_state["search_keywords"]:
        st.session_state["search_keywords"].append(new_search_kw.strip())
        if new_search_kw.strip() not in st.session_state["keyword_pool"]:
            st.session_state["keyword_pool"].append(new_search_kw.strip())
        st.rerun()

    current_search = st.multiselect("검색 키워드", st.session_state["search_keywords"], default=st.session_state["search_keywords"], label_visibility="collapsed", key="active_kw")
    if set(current_search) != set(st.session_state["search_keywords"]):
        st.session_state["search_keywords"] = current_search
        st.rerun()

    if st.button("🔄 초기화", use_container_width=True):
        st.session_state["keyword_pool"] = list(DEFAULT_KEYWORDS)
        st.session_state["search_keywords"] = list(DEFAULT_KEYWORDS[:4])
        st.rerun()

    st.divider()
    run_search = st.button("🔍 뉴스 검색", type="primary", use_container_width=True)

# ─── 검색 실행 ───
if run_search:
    if not st.session_state["search_keywords"]:
        st.error("검색 키워드를 1개 이상 추가하세요.")
        st.stop()
    with st.spinner("5개 언론사에서 뉴스 수집 중..."):
        collect_result = collect_articles(st.session_state["search_keywords"], WINDOW_MAP[time_window])
        norm_result = normalize_articles(collect_result["raw_articles"])
    st.session_state["search_result"] = collect_result
    st.session_state["normalized"] = norm_result["normalized_articles"]
    for k in ["scored_articles", "trends", "sentiment_overview", "source_reactions", "briefing_html", "analyzed_articles"]:
        st.session_state.pop(k, None)
    st.rerun()

# ─── 결과 표시 ───
if "normalized" in st.session_state and st.session_state["normalized"]:
    articles = st.session_state["normalized"]
    collect_result = st.session_state["search_result"]

    tab1, tab2, tab3, tab4 = st.tabs(["📰 검색 결과", "🎯 스코어링 & 대시보드", "📊 분석 리포트", "🏗️ 아키텍처 문서"])

    # ━━━ Tab 1: 검색 결과 ━━━
    with tab1:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("수집 기사", collect_result["total_count"])
        k2.metric("정규화 후", len(articles))
        k3.metric("언론사", len(collect_result["source_counts"]))
        k4.metric("실패", len(collect_result["failed_sources"]))

        df = pd.DataFrame(articles)
        if not df.empty:
            c1, c2 = st.columns(2)
            with c1:
                if "source_name" in df.columns:
                    fig = px.bar(df["source_name"].value_counts().reset_index(), x="source_name", y="count", title="언론사별 기사 수", color="source_name")
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                if "section" in df.columns:
                    fig = px.pie(df["section"].value_counts().reset_index(), values="count", names="section", title="섹션 분포")
                    st.plotly_chart(fig, use_container_width=True)

            st.subheader("기사 목록")
            for i, a in enumerate(articles[:50], 1):
                st.markdown(f"**{i}.** [{a['title']}]({a['url']}) — {a['source_name']} | {a.get('published_at','')[:10]}")

    # ━━━ Tab 2: 스코어링 & 대시보드 ━━━
    with tab2:
        # 목적 선택 (스코어링에 필요)
        purpose_options = list(PURPOSES.keys())
        selected_purpose = st.radio("분석 목적", purpose_options, horizontal=True, label_visibility="collapsed", index=0)
        purpose_id = PURPOSES[selected_purpose]["id"]

        if st.button("🎯 스코어링 분석 실행", type="primary", use_container_width=True):
            progress = st.progress(0, "중복 제거 중...")

            # Step 1: Dedup
            dedup_result = dedup_and_vectorize(articles)
            filtered = dedup_result["filtered_articles"]
            progress.progress(0.2, f"중복 제거 완료 ({len(filtered)}건)")

            # Step 2: Insight Analysis
            progress.progress(0.3, "Bedrock 기사 분석 중...")
            analyzed = analyze_articles(filtered, selected_role, purpose_id)
            progress.progress(0.5, f"분석 완료 ({len(analyzed)}건)")

            # Step 3: User intent embedding
            progress.progress(0.6, "사용자 의도 벡터 생성 중...")
            user_intent_text = build_user_intent_text(role_key, purpose_id, st.session_state["search_keywords"], [])
            user_vector = np.array(get_embedding(user_intent_text), dtype=np.float32)

            # Step 4: Score each article
            progress.progress(0.7, "기사별 스코어링 중...")
            # cluster size 계산 (opportunity_type 기준)
            opp_counts = Counter(a.get("opportunity_type", "other") for a in analyzed)
            max_cluster = max(opp_counts.values()) if opp_counts else 1

            for art in analyzed:
                # article embedding
                art_text = build_article_intent_text(art)
                try:
                    art_vector = np.array(get_embedding(art_text), dtype=np.float32)
                except Exception:
                    art_vector = np.zeros_like(user_vector)

                # role keyword match
                rk_score = calculate_role_keyword_match_score(user_vector, art_vector)
                art["role_keyword_match_score"] = rk_score
                art["role_keyword_match_reason"] = f"직군 의도와 기사 벡터 유사도 {rk_score:.2f}"

                # recency
                try:
                    pub_dt = datetime.fromisoformat(art.get("published_at", ""))
                except Exception:
                    pub_dt = datetime.now()
                rec_score = calculate_recency_score(pub_dt)
                art["recency_score"] = rec_score

                # hotness
                cluster_size = opp_counts.get(art.get("opportunity_type", "other"), 1)
                hot_score = calculate_hotness_score(cluster_size, max_cluster)
                art["hotness_score"] = hot_score

                # source weight
                src_weight = get_source_weight(
                    art.get("source_id", ""),
                    role_key,
                    art.get("section", ""),
                    purpose_id,
                    art.get("opportunity_type", ""),
                )
                art["source_weight"] = src_weight

                # noise penalty
                noise_penalty = 0.7 if any(nk in art.get("title", "").lower() for nk in NOISE_KEYWORDS) else 1.0

                # final score (importance → llm_importance 매핑)
                art["llm_importance"] = art.get("importance", 5)
                final = calculate_final_score(art, src_weight, rk_score, rec_score, hot_score, noise_penalty)
                art["final_score_100"] = final

                # score reason
                art["score_reason"] = build_score_reason(art, final, src_weight, rk_score)

            # Sort by final_score_100
            analyzed.sort(key=lambda x: x.get("final_score_100", 0), reverse=True)

            # Step 5: Trends & Sentiment
            progress.progress(0.9, "트렌드/여론 분석 중...")
            trends = extract_trend_keywords(analyzed)
            sentiment_ov = calculate_sentiment_overview(analyzed)
            source_rx = calculate_source_reactions(analyzed)

            st.session_state["scored_articles"] = analyzed
            st.session_state["trends"] = trends
            st.session_state["sentiment_overview"] = sentiment_ov
            st.session_state["source_reactions"] = source_rx
            progress.progress(1.0, "✅ 스코어링 완료!")
            st.rerun()

        # ── 스코어링 결과 표시 ──
        if "scored_articles" in st.session_state:
            scored = st.session_state["scored_articles"]
            trends = st.session_state["trends"]
            sentiment_ov = st.session_state["sentiment_overview"]
            source_rx = st.session_state["source_reactions"]

            # A) Top 5 Priority News
            st.subheader("🏆 Top 5 Priority News")
            for rank, art in enumerate(scored[:5], 1):
                left, right = st.columns([7, 3])
                with left:
                    st.markdown(f"### #{rank} {art.get('title','')}")
                    st.caption(f"{art.get('source_name','')} | {art.get('section','')} | {art.get('published_at','')[:10]}")
                    with st.expander("📊 Score Breakdown"):
                        s1, s2, s3, s4 = st.columns(4)
                        s1.metric("LLM 중요도", f"{art.get('llm_importance',5)}/10")
                        s2.metric("MZC 관련도", f"{art.get('relevance_to_mzc',0):.2f}")
                        s3.metric("목적 적합도", f"{art.get('purpose_fit',0):.2f}")
                        s4.metric("직군/키워드", f"{art.get('role_keyword_match_score',0):.2f}")
                        s5, s6, s7, s8 = st.columns(4)
                        s5.metric("감성", art.get("sentiment", "-"))
                        s6.metric("최신성", f"{art.get('recency_score',0):.2f}")
                        s7.metric("Hotness", f"{art.get('hotness_score',0):.2f}")
                        s8.metric("언론사 가중치", f"{art.get('source_weight',1.0):.2f}")
                    st.info(f"💡 {art.get('score_reason','')}")
                    st.write(f"**요약:** {art.get('summary_ko', art.get('snippet','')[:200])}")
                    st.write(f"**왜 중요한가:** {art.get('why_it_matters','')}")
                    st.write(f"**추천 액션:** {art.get('suggested_action','')}")
                    st.write(f"**직군 매칭:** {art.get('role_keyword_match_reason','')}")
                    st.link_button("원문 보기", art.get("url", "#"))
                with right:
                    st.markdown(f"<div style='text-align:center;padding:20px;'><span style='font-size:12px;color:gray;'>IMPACT SCORE</span><br><span style='font-size:52px;font-weight:bold;color:#FF4B4B;'>{art.get('final_score_100',0)}</span></div>", unsafe_allow_html=True)
                st.divider()

            # B) Trends
            st.subheader("📈 Current Trends")
            if trends:
                tdf = pd.DataFrame(trends[:10])
                if "trend_keyword" in tdf.columns:
                    fig = px.bar(tdf, x="trend_keyword", y="trend_score", title="Top 10 트렌드 키워드", color="trend_score")
                    st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(tdf[["trend_keyword", "trend_score", "article_count", "avg_final_score", "negative_ratio"]].round(2), use_container_width=True)

            # C) Sentiment
            st.subheader("💭 Overall Sentiment")
            if sentiment_ov:
                ss1, ss2, ss3, ss4 = st.columns(4)
                ss1.metric("Sentiment Index", f"{sentiment_ov.get('sentiment_index',0):.2f}")
                ss2.metric("긍정", sentiment_ov.get("positive_count", 0))
                ss3.metric("중립", sentiment_ov.get("neutral_count", 0))
                ss4.metric("부정", sentiment_ov.get("negative_count", 0))
                st.caption(f"여론: **{sentiment_ov.get('label', '')}**")

                pie_df = pd.DataFrame({"감성": ["긍정","중립","부정"], "수": [sentiment_ov.get("positive_count",0), sentiment_ov.get("neutral_count",0), sentiment_ov.get("negative_count",0)]})
                fig = px.pie(pie_df, names="감성", values="수", color="감성", color_discrete_map={"긍정":"green","중립":"gray","부정":"red"})
                st.plotly_chart(fig, use_container_width=True)

                tp, tn = st.columns(2)
                with tp:
                    st.markdown("**Top 3 긍정 기사**")
                    for a in sentiment_ov.get("top_positive", [])[:3]:
                        st.write(f"- {a.get('title','')}")
                with tn:
                    st.markdown("**Top 3 부정 기사**")
                    for a in sentiment_ov.get("top_negative", [])[:3]:
                        st.write(f"- {a.get('title','')}")

            # D) Source Reactions
            st.subheader("🔥 Source Hot/Cold Reaction")
            if source_rx:
                rx_df = pd.DataFrame(source_rx)
                if "source_name" in rx_df.columns and "source_reaction_score" in rx_df.columns:
                    color_map = {"HOT": "#ff4444", "HOT RISK": "#8b0000", "WARM": "#ff8c00", "COLD": "#4169e1"}
                    fig = px.bar(rx_df, x="source_name", y="source_reaction_score", color="reaction_label", title="언론사별 반응 점수", color_discrete_map=color_map)
                    st.plotly_chart(fig, use_container_width=True)

                    for _, row in rx_df.iterrows():
                        badge = row.get("reaction_label", "COLD")
                        color = color_map.get(badge, "gray")
                        st.markdown(f"<span style='background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;'>{badge}</span> **{row.get('source_name','')}** — 점수: {row.get('source_reaction_score',0):.1f} | 기사: {row.get('article_count',0)}건 | 부정비율: {row.get('negative_ratio',0):.0%}", unsafe_allow_html=True)

    # ━━━ Tab 3: 분석 리포트 ━━━
    with tab3:
        st.subheader("분석 목적 선택")
        rpt_purpose = st.radio("목적", list(PURPOSES.keys()), horizontal=True, label_visibility="collapsed", index=0, key="rpt_purpose")
        rpt_purpose_id = PURPOSES[rpt_purpose]["id"]

        if st.button("📊 리포트 생성", type="primary", use_container_width=True):
            progress = st.progress(0, "분석 중...")
            dedup_result = dedup_and_vectorize(articles)
            filtered = dedup_result["filtered_articles"]
            progress.progress(0.3)
            analyzed = analyze_articles(filtered, selected_role, rpt_purpose_id)
            progress.progress(0.6)
            briefing_content = generate_briefing(selected_role, rpt_purpose_id, analyzed)
            stats = {"total_collected": len(articles), "after_dedup": len(filtered), "analyzed": len(analyzed), "high_importance": sum(1 for a in analyzed if a.get("importance",0)>=8), "avg_purpose_fit": sum(a.get("purpose_fit",0) for a in analyzed)/max(len(analyzed),1)}
            briefing_html = render_briefing_html(selected_role, rpt_purpose, briefing_content, analyzed, stats)
            st.session_state["briefing_html"] = briefing_html
            st.session_state["analyzed_articles"] = analyzed
            progress.progress(1.0, "✅ 완료!")
            st.rerun()

        if "briefing_html" in st.session_state:
            st.subheader("📄 리포트 미리보기")
            st.components.v1.html(st.session_state["briefing_html"], height=600, scrolling=True)

    # ━━━ Tab 4: 아키텍처 문서 ━━━
    with tab4:
        st.subheader("🏗️ 아키텍처 설계서")
        st.caption("Bedrock이 프로젝트 아키텍처 설계서를 자동 생성합니다.")
        if st.button("📐 아키텍처 설계서 생성", type="primary", use_container_width=True):
            with st.spinner("Bedrock으로 설계서 생성 중..."):
                from agents.architecture_doc import generate_architecture_doc
                arch_html = generate_architecture_doc()
                st.session_state["arch_html"] = arch_html
                st.rerun()

        if "arch_html" in st.session_state:
            st.components.v1.html(st.session_state["arch_html"], height=600, scrolling=True)
            st.download_button("📄 HTML 다운로드", st.session_state["arch_html"], "architecture_document.html", "text/html", use_container_width=True)

else:
    st.info("👈 사이드바에서 키워드를 설정하고 검색을 실행하세요.")
