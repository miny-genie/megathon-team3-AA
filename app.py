"""
app.py - MZC Sales Radar (Production UI)
─────────────────────────────────────────
No emoji. No decorative landing. Dense, professional internal SaaS tool.
"""
import sys, os
from datetime import datetime
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

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
from services.bedrock_client import get_embedding

st.set_page_config(page_title="MZC Sales Radar", page_icon=None, layout="wide", initial_sidebar_state="collapsed")

# ─── CSS ───
st.markdown("""<style>
[data-testid="stAppViewContainer"] { background: #fafbfc; }
.block-container { padding-top: 1rem; }
.sticky-bar { background:#fff; border-bottom:1px solid #e1e4e8; padding:10px 16px; margin:-1rem -1rem 1rem -1rem; }
.metric-row { display:flex; gap:12px; margin:8px 0; }
.metric-box { background:#fff; border:1px solid #e1e4e8; border-radius:4px; padding:10px 14px; flex:1; }
.metric-box .val { font-size:1.4rem; font-weight:700; color:#24292f; }
.metric-box .lbl { font-size:0.72rem; color:#656d76; text-transform:uppercase; letter-spacing:0.5px; }
.type-badge { display:inline-block; padding:1px 6px; border-radius:3px; font-size:0.7rem; font-weight:600; margin-right:6px; }
.badge-breaking { background:#fde8e8; color:#b91c1c; }
.badge-policy { background:#dbeafe; color:#1e40af; }
.badge-sales { background:#dcfce7; color:#166534; }
.badge-proposal { background:#fef3c7; color:#92400e; }
.badge-competitive { background:#f3e8ff; color:#6b21a8; }
.badge-trend { background:#e0f2fe; color:#075985; }
.badge-risk { background:#fee2e2; color:#991b1b; }
.score-num { font-size:1.8rem; font-weight:800; color:#0969da; line-height:1; }
.score-label { font-size:0.65rem; color:#656d76; text-transform:uppercase; }
.chip { display:inline-block; border:1px solid #d0d7de; border-radius:3px; padding:2px 8px; margin:2px; font-size:0.78rem; cursor:pointer; background:#fff; }
.chip-active { background:#ddf4ff; border-color:#54aeff; }
.editor-left { border:1px solid #d0d7de; border-radius:4px; padding:12px; background:#fff; min-height:350px; }
.editor-right { border:1px solid #1f883d; border-radius:4px; padding:12px; background:#f6fef9; min-height:350px; }
.section-title { font-size:0.85rem; font-weight:600; color:#24292f; text-transform:uppercase; letter-spacing:0.5px; margin:16px 0 8px 0; border-bottom:1px solid #e1e4e8; padding-bottom:4px; }
</style>""", unsafe_allow_html=True)

# ─── Session State Init ───
defaults = {"phase": "landing", "keyword_pool": list(DEFAULT_KEYWORDS), "search_keywords": [], "header_expanded": True, "alert_settings": {}}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ═══════════════════════════════════════
# 1. LANDING PAGE
# ═══════════════════════════════════════
if st.session_state["phase"] == "landing":
    st.markdown("## MZC Sales Radar")
    st.caption("메가존클라우드 영업 및 프리세일즈를 위한 뉴스 기반 영업 인텔리전스")
    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        persona = st.selectbox("직군 선택", list(ROLES.keys()), index=0)
        purpose_sel = st.selectbox("분석 목적", list(PURPOSES.keys()), index=0)
    with col2:
        kw_input = st.text_input("키워드 입력 (쉼표 구분)", placeholder="AWS, 생성형 AI, 금융 클라우드, 보안")
        period = st.radio("조회 기간", list(WINDOW_MAP.keys()), horizontal=True, index=0)

    if not ROLES[persona]["supported"]:
        st.warning("현재 MVP에서는 영업과 프리세일즈 워크플로우만 실행됩니다.")

    if st.button("분석 시작", type="primary", disabled=not ROLES[persona]["supported"]):
        kws = [k.strip() for k in kw_input.split(",") if k.strip()] if kw_input else DEFAULT_KEYWORDS[:4]
        st.session_state.update({
            "selected_role": persona,
            "role_key": ROLES[persona]["target_role"],
            "selected_purpose": purpose_sel,
            "purpose_id": PURPOSES[purpose_sel]["id"],
            "search_keywords": kws,
            "keyword_pool": list(set(DEFAULT_KEYWORDS + kws)),
            "time_window": WINDOW_MAP[period],
            "phase": "loading",
        })
        st.rerun()
    st.stop()

# ═══════════════════════════════════════
# LOADING
# ═══════════════════════════════════════
if st.session_state["phase"] == "loading":
    st.markdown("### 분석 진행 중...")
    progress = st.progress(0)
    kws = st.session_state["search_keywords"]
    window = st.session_state["time_window"]
    role_key = st.session_state["role_key"]
    purpose_id = st.session_state["purpose_id"]

    progress.progress(0.1, "뉴스 수집 중...")
    collect_result = collect_articles(kws, window)
    norm_result = normalize_articles(collect_result["raw_articles"])
    articles = norm_result["normalized_articles"]
    progress.progress(0.3, f"{len(articles)}건 수집 완료")

    progress.progress(0.4, "중복/노이즈 제거 중...")
    dedup_result = dedup_and_vectorize(articles)
    filtered = dedup_result["filtered_articles"]
    progress.progress(0.5)

    progress.progress(0.6, "Bedrock 분석 중...")
    analyzed = analyze_articles(filtered, st.session_state["selected_role"], purpose_id)
    progress.progress(0.7)

    progress.progress(0.8, "스코어링 중...")
    user_intent = build_user_intent_text(role_key, purpose_id, kws, [])
    try:
        user_vector = np.array(get_embedding(user_intent), dtype=np.float32)
    except Exception:
        user_vector = np.zeros(1024, dtype=np.float32)

    opp_counts = Counter(a.get("opportunity_type", "other") for a in analyzed)
    max_cluster = max(opp_counts.values()) if opp_counts else 1

    for art in analyzed:
        art_vector = np.array(art["embedding"], dtype=np.float32) if "embedding" in art else np.zeros_like(user_vector)
        rk = calculate_role_keyword_match_score(user_vector, art_vector)
        art["role_keyword_match_score"] = rk
        art["recency_score"] = calculate_recency_score(art.get("published_at", ""))
        art["hotness_score"] = calculate_hotness_score(opp_counts.get(art.get("opportunity_type","other"),1), max_cluster)
        art["source_weight"] = get_source_weight(art.get("source_id",""), role_key, art.get("section",""), purpose_id, art.get("opportunity_type",""))
        art["llm_importance"] = art.get("importance", 5)
        noise_p = 0.7 if any(nk in art.get("title","").lower() for nk in NOISE_KEYWORDS) else 1.0
        art["final_score_100"] = calculate_final_score(art, art["source_weight"], rk, art["recency_score"], art["hotness_score"], noise_p)
        art["score_reason"] = build_score_reason(art, art["final_score_100"], art["source_weight"], rk)

    analyzed.sort(key=lambda x: x.get("final_score_100", 0), reverse=True)
    progress.progress(0.9, "트렌드/여론 분석 중...")
    trends = extract_trend_keywords(analyzed)
    sentiment_ov = calculate_sentiment_overview(analyzed)
    source_rx = calculate_source_reactions(analyzed)

    st.session_state.update({
        "articles": analyzed, "trends": trends, "sentiment_overview": sentiment_ov,
        "source_reactions": source_rx, "collect_result": collect_result,
        "dedup_result": dedup_result, "phase": "dashboard", "last_analysis": datetime.now().strftime("%H:%M"),
    })
    progress.progress(1.0, "완료")
    st.rerun()

# ═══════════════════════════════════════
# 2-5. DASHBOARD
# ═══════════════════════════════════════
if st.session_state["phase"] == "dashboard":
    articles = st.session_state["articles"]
    trends = st.session_state["trends"]
    sentiment_ov = st.session_state["sentiment_overview"]
    source_rx = st.session_state["source_reactions"]

    # ─── 2. STICKY HEADER ───
    with st.container():
        hcol1, hcol2 = st.columns([10, 1])
        with hcol1:
            summary = f"{st.session_state['selected_role']} | {st.session_state['selected_purpose']} | {len(articles)}건 분석 | {st.session_state.get('last_analysis','')}"
            if not st.session_state["header_expanded"]:
                st.caption(summary)
            else:
                st.markdown(f"**{summary}**")
        with hcol2:
            if st.button("접기" if st.session_state["header_expanded"] else "펼치기", key="toggle_hdr"):
                st.session_state["header_expanded"] = not st.session_state["header_expanded"]
                st.rerun()

        if st.session_state["header_expanded"]:
            fc1, fc2, fc3 = st.columns([2, 4, 2])
            with fc1:
                new_role = st.selectbox("직군", [r for r in ROLES if ROLES[r]["supported"]], index=0, key="hdr_role")
                new_purpose = st.selectbox("목적", list(PURPOSES.keys()), index=0, key="hdr_purpose")
            with fc2:
                # Keyword chips
                active_kws = st.multiselect("활성 키워드", st.session_state["keyword_pool"], default=st.session_state["search_keywords"], key="hdr_kws")
                if st.button("AI 추천 키워드 생성"):
                    with st.spinner("추천 중..."):
                        r = recommend_keywords(active_kws[:5], new_role, PURPOSES[new_purpose]["id"])
                        for kw in r.get("recommended_keywords", []):
                            if kw not in st.session_state["keyword_pool"]:
                                st.session_state["keyword_pool"].append(kw)
                        st.rerun()
            with fc3:
                if st.button("조건 적용 및 재분석", type="primary"):
                    st.session_state.update({
                        "selected_role": new_role, "role_key": ROLES[new_role]["target_role"],
                        "selected_purpose": new_purpose, "purpose_id": PURPOSES[new_purpose]["id"],
                        "search_keywords": active_kws, "phase": "loading",
                    })
                    st.rerun()
            st.markdown("---")

    # ─── 3. SUMMARY DASHBOARD ───
    # KPI
    cr = st.session_state["collect_result"]
    dr = st.session_state["dedup_result"]
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("수집", cr["total_count"])
    m2.metric("중복 제거", dr["duplicate_count"])
    m3.metric("노이즈 제거", dr["noise_count"])
    m4.metric("분석 완료", len(articles))
    m5.metric("중요도 8+", sum(1 for a in articles if a.get("importance",0)>=8))
    m6.metric("평균 매칭도", f"{np.mean([a.get('role_keyword_match_score',0) for a in articles]):.2f}" if articles else "0")

    # Insight Summary
    st.markdown('<div class="section-title">INSIGHT SUMMARY</div>', unsafe_allow_html=True)
    if articles:
        top = articles[0]
        label = sentiment_ov.get("label", "") if sentiment_ov else ""
        st.markdown(f"**Context:** 현재 시장은 '{label}' 상태이며, 주요 기회 유형은 '{top.get('opportunity_type','')}'입니다.")
        st.markdown(f"**Recommended Action:** {top.get('suggested_action', '주요 기사를 확인하고 고객 접점을 준비하세요.')}")

    # Top 5 Priority News
    st.markdown('<div class="section-title">TOP 5 PRIORITY NEWS</div>', unsafe_allow_html=True)
    for rank, art in enumerate(articles[:5], 1):
        left, right = st.columns([9, 1])
        with left:
            opp = art.get("opportunity_type", "other")
            badge_map = {"sales_opportunity":"badge-sales","lead_generation":"badge-sales","customer_signal":"badge-sales","proposal_evidence":"badge-proposal","competitive_intelligence":"badge-competitive","competitor_signal":"badge-competitive","market_trend":"badge-trend","security_risk":"badge-risk"}
            badge_cls = badge_map.get(opp, "badge-trend")
            label_map = {"sales_opportunity":"SALES","lead_generation":"LEAD","customer_signal":"SIGNAL","proposal_evidence":"PROPOSAL","competitive_intelligence":"COMPETITIVE","competitor_signal":"COMPETITIVE","market_trend":"TREND","security_risk":"RISK"}
            badge_lbl = label_map.get(opp, opp.upper()[:8])
            st.markdown(f'<span class="type-badge {badge_cls}">{badge_lbl}</span> **{art.get("title","")}**', unsafe_allow_html=True)
            st.caption(f'{art.get("source_name","")} | {art.get("published_at","")[:10]} | 감성: {art.get("sentiment","")} | 매칭: {art.get("role_keyword_match_score",0):.2f}')
            with st.expander("상세"):
                st.write(f'**요약:** {art.get("summary_ko", art.get("snippet","")[:200])}')
                st.write(f'**Why:** {art.get("why_it_matters","")}')
                st.write(f'**Action:** {art.get("suggested_action","")}')
                st.write(f'**Score:** {art.get("score_reason","")}')
                st.link_button("원문", art.get("url","#"))
        with right:
            st.markdown(f'<div class="score-label">SCORE</div><div class="score-num">{art.get("final_score_100",0)}</div>', unsafe_allow_html=True)
        st.markdown("---")

    # Charts
    st.markdown('<div class="section-title">TRENDS / SENTIMENT / SOURCE REACTION</div>', unsafe_allow_html=True)
    t1, t2, t3 = st.columns(3)
    with t1:
        if trends:
            tdf = pd.DataFrame(trends[:8])
            if "trend_keyword" in tdf.columns:
                fig = px.bar(tdf, x="trend_score", y="trend_keyword", orientation="h", title="Trend Keywords")
                fig.update_layout(height=250, margin=dict(l=0,r=0,t=30,b=0), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
    with t2:
        if sentiment_ov:
            fig = go.Figure(go.Indicator(mode="gauge+number", value=sentiment_ov.get("sentiment_index",0), title={"text":f"Sentiment ({sentiment_ov.get('label','')})"},
                gauge={"axis":{"range":[-1,1]},"bar":{"color":"#0969da"},"steps":[{"range":[-1,-0.25],"color":"#fee2e2"},{"range":[-0.25,0.25],"color":"#f3f4f6"},{"range":[0.25,1],"color":"#dcfce7"}]}))
            fig.update_layout(height=250, margin=dict(l=20,r=20,t=40,b=0))
            st.plotly_chart(fig, use_container_width=True)
    with t3:
        if source_rx:
            rx_df = pd.DataFrame(source_rx)
            if "source_name" in rx_df.columns:
                fig = px.bar(rx_df, x="source_reaction_score", y="source_name", orientation="h", color="reaction_label",
                    color_discrete_map={"HOT":"#dc2626","HOT RISK":"#7f1d1d","WARM":"#ea580c","COLD":"#2563eb"}, title="Source Reaction")
                fig.update_layout(height=250, margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(fig, use_container_width=True)

    # ─── 4. SIDE-BY-SIDE EDITOR ───
    st.markdown('<div class="section-title">DOCUMENT EDITOR</div>', unsafe_allow_html=True)
    ed_left, ed_right = st.columns(2)

    with ed_left:
        st.markdown("**참조 (V1) - 주요 기사 원문**")
        ref_text = "\n\n---\n\n".join([f"[{a.get('source_name','')}] {a.get('title','')}\n{a.get('snippet','')[:300]}" for a in articles[:5]])
        st.text_area("참조 텍스트", ref_text, height=350, key="ref_v1", label_visibility="collapsed")

    with ed_right:
        st.markdown("**초안 (V+) - AI 생성 브리핑**")
        if "draft_text" not in st.session_state:
            st.session_state["draft_text"] = ""
        if st.button("초안 생성", type="primary"):
            with st.spinner("Bedrock 초안 작성 중..."):
                content = generate_briefing(st.session_state["selected_role"], st.session_state["purpose_id"], articles[:10])
                st.session_state["draft_text"] = content
                stats = {"total_collected":len(articles),"after_dedup":len(articles),"analyzed":len(articles),"high_importance":sum(1 for a in articles if a.get("importance",0)>=8),"avg_purpose_fit":0.7}
                st.session_state["briefing_html"] = render_briefing_html(st.session_state["selected_role"], st.session_state["selected_purpose"], content, articles[:10], stats)
                st.rerun()
        draft = st.text_area("초안 편집", st.session_state["draft_text"], height=350, key="draft_v_plus", label_visibility="collapsed")
        st.session_state["draft_text"] = draft

    # Action toolbar
    act1, act2, act3, act4, act5 = st.columns(5)
    with act1:
        if "briefing_html" in st.session_state:
            st.download_button("HTML 다운로드", st.session_state["briefing_html"], "briefing.html", "text/html", use_container_width=True)
    with act2:
        if st.button("Google Docs 내보내기", use_container_width=True):
            st.info("Google Docs export는 운영 연동 대상입니다. 현재는 HTML 다운로드를 제공합니다.")
    with act3:
        if "briefing_html" in st.session_state:
            st.download_button("DOCX", f"<html><head><meta charset='utf-8'></head><body>{st.session_state['briefing_html']}</body></html>".encode(), "briefing.doc", "application/msword", use_container_width=True)
    with act4:
        if st.button("아키텍처 문서 생성", use_container_width=True):
            with st.spinner("생성 중..."):
                from agents.architecture_doc import generate_architecture_doc
                st.session_state["arch_html"] = generate_architecture_doc()
                st.rerun()
    with act5:
        pass  # Slack alert button below

    if "arch_html" in st.session_state:
        with st.expander("아키텍처 문서 미리보기"):
            st.components.v1.html(st.session_state["arch_html"], height=400, scrolling=True)
            st.download_button("아키텍처 HTML 다운로드", st.session_state["arch_html"], "architecture.html", "text/html")

    # ─── 5. SLACK ALERT SETTINGS ───
    st.markdown('<div class="section-title">ALERT SETTINGS</div>', unsafe_allow_html=True)
    with st.expander("Slack Alert 설정"):
        al1, al2 = st.columns(2)
        with al1:
            st.markdown("**정기 요약 보고**")
            sched_enabled = st.checkbox("활성화", key="sched_on", value=st.session_state["alert_settings"].get("scheduled", False))
            sched_time = st.time_input("발송 시각", value=datetime.strptime("08:00", "%H:%M").time(), key="sched_time")
        with al2:
            st.markdown("**핵심 이슈 실시간 알림**")
            rt_enabled = st.checkbox("활성화", key="rt_on", value=st.session_state["alert_settings"].get("realtime", False))
            threshold = st.slider("임팩트 스코어 임계치", 50, 100, 85, key="rt_threshold")
            alert_count = sum(1 for a in articles if a.get("final_score_100",0) >= threshold)
            st.caption(f"현재 조건에서 알림 대상: {alert_count}건")

        st.markdown("**모니터링 기간**")
        mon_type = st.radio("유형", ["상시 모니터링", "프로젝트 기반"], horizontal=True, key="mon_type")
        if mon_type == "프로젝트 기반":
            mon_dates = st.date_input("기간", value=(datetime.now().date(), datetime.now().date()), key="mon_dates")

        st.caption("연결: MegazoneCloud Slack Workspace / #sales-radar-alerts")

        if st.button("알림 설정 저장"):
            st.session_state["alert_settings"] = {
                "scheduled": sched_enabled, "schedule_time": str(sched_time),
                "realtime": rt_enabled, "threshold": threshold,
                "monitoring": mon_type,
            }
            st.success("알림 설정이 저장되었습니다.")

    # ─── Footer ───
    st.markdown("---")
    if st.button("처음으로"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()
