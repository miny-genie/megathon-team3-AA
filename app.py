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
[data-testid="stAppViewContainer"] { background: #f5f7fa; }
.block-container { padding-top: 1rem; max-width: 1200px; }
.section-title { font-size:0.9rem; font-weight:700; color:#1a1a1a; margin:20px 0 12px 0; padding-bottom:6px; border-bottom:2px solid #e1e4e8; }
.metric-box { background:#fff; border:1px solid #e1e4e8; border-radius:6px; padding:12px 16px; }
.metric-box .val { font-size:1.5rem; font-weight:700; color:#1a73e8; }
.metric-box .lbl { font-size:0.72rem; color:#5f6368; text-transform:uppercase; }
[data-testid="stMetric"] { background:#fff; border:1px solid #e8eaed; border-radius:6px; padding:8px 12px; }
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
        kws = [k.strip() for k in kw_input.split(",") if k.strip()] if kw_input else DEFAULT_KEYWORDS
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
    # 상위 20개만 LLM 분석 (속도 최적화: 20개 × Haiku = ~25초)
    articles_to_analyze = filtered[:20]
    analyzed = analyze_articles(articles_to_analyze, st.session_state["selected_role"], purpose_id)
    # 나머지는 분석 없이 기본값으로 추가
    for art in filtered[20:]:
        art.update({"importance": 3, "sentiment": "neutral", "opportunity_type": "other", "relevance_to_mzc": 0.3, "purpose_fit": 0.3, "summary_ko": art.get("snippet","")[:100], "why_it_matters": "", "suggested_action": "", "target_role": "both"})
        analyzed.append(art)
    progress.progress(0.7)

    progress.progress(0.8, "스코어링 중...")
    # 이유: Embedding 호출을 최소화. user intent 1번만 호출하고 기사는 있는 것만 사용.
    user_intent = build_user_intent_text(role_key, purpose_id, kws, [])
    try:
        user_vector = np.array(get_embedding(user_intent), dtype=np.float32)
    except Exception:
        user_vector = None

    opp_counts = Counter(a.get("opportunity_type", "other") for a in analyzed)
    max_cluster = max(opp_counts.values()) if opp_counts else 1

    for art in analyzed:
        # role_keyword_match: embedding 있으면 cosine, 없으면 키워드 겹침 비율
        if user_vector is not None and "embedding" in art and art["embedding"]:
            art_vector = np.array(art["embedding"], dtype=np.float32)
            rk = calculate_role_keyword_match_score(user_vector, art_vector)
        else:
            # fallback: 키워드 포함 비율로 간이 매칭
            title_lower = art.get("title", "").lower()
            match_count = sum(1 for k in kws if k.lower() in title_lower)
            rk = min(match_count / max(len(kws), 1), 1.0)
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

    # Insight Summary - 실제 데이터 기반 종합 분석
    st.markdown('<div class="section-title">INSIGHT SUMMARY</div>', unsafe_allow_html=True)
    if articles:
        pos_count = sum(1 for a in articles if a.get("sentiment") == "positive")
        neg_count = sum(1 for a in articles if a.get("sentiment") == "negative")
        neu_count = len(articles) - pos_count - neg_count
        top_opps = Counter(a.get("opportunity_type","other") for a in articles[:15]).most_common(3)
        top_sources = Counter(a.get("source_name","") for a in articles).most_common(3)
        high_imp = [a for a in articles if a.get("importance",0) >= 7]
        avg_score = np.mean([a.get("final_score_100",0) for a in articles[:20]]) if articles else 0
        top_keywords = Counter()
        for a in articles[:20]:
            for kw in st.session_state.get("search_keywords", []):
                if kw.lower() in a.get("title","").lower():
                    top_keywords[kw] += 1
        hot_kws = top_keywords.most_common(3)

        opp_labels = {"sales_opportunity":"영업 기회","lead_generation":"신규 리드/투자 신호","customer_signal":"고객 IT 투자 신호","proposal_evidence":"규제/정책 변화","competitive_intelligence":"경쟁사 동향","competitor_signal":"경쟁사 수주/MOU","market_trend":"기술 트렌드","security_risk":"보안 리스크/장애","cloud_migration":"클라우드 전환","genai_opportunity":"생성형 AI 기회","other":"기타"}

        # 한 줄 요약
        top_opp_label = opp_labels.get(top_opps[0][0], "기타") if top_opps else "기타"
        sentiment_word = "부정 리스크 우세" if neg_count > pos_count else ("긍정 신호 우세" if pos_count > neg_count else "중립 혼재")
        one_liner = f"{len(articles)}건 분석 결과, '{top_opp_label}' 유형이 가장 많고 여론은 {sentiment_word}입니다. 평균 임팩트 {avg_score:.0f}점."
        st.markdown(f"""<div style="font-size:0.95rem; font-weight:600; color:#1a73e8; margin-bottom:8px;">{one_liner}</div>""", unsafe_allow_html=True)

        # 실제 분석 텍스트 구성
        lines = []
        lines.append(f"<b>[분석 범위]</b> {len(articles)}건 기사 분석 완료. 평균 임팩트 스코어 {avg_score:.1f}점. 중요도 7+ 기사 {len(high_imp)}건 감지.")
        if hot_kws:
            lines.append(f"<b>[핵심 키워드]</b> 가장 많이 언급된 키워드: {', '.join(f'{k}({v}건)' for k,v in hot_kws)}.")
        lines.append(f"<b>[기회 유형]</b> 상위 기회: {', '.join(f'{opp_labels.get(o[0],o[0])}({o[1]}건)' for o in top_opps)}.")
        lines.append(f"<b>[여론 동향]</b> 긍정 {pos_count}건 / 중립 {neu_count}건 / 부정 {neg_count}건. {'부정 기사가 많아 리스크 대응 우선.' if neg_count > pos_count else '긍정 우세로 시장 확장 기회 활용 가능.'}")
        lines.append(f"<b>[매체 분포]</b> 주요 보도: {', '.join(f'{s[0]}({s[1]}건)' for s in top_sources)}.")
        if articles[0].get("why_it_matters"):
            lines.append(f"<b>[최우선 기사 시사점]</b> {articles[0]['why_it_matters']}")
        if articles[0].get("suggested_action"):
            lines.append(f"<b>[권장 액션]</b> {articles[0]['suggested_action']}")

        st.markdown(f"""<div style="background:#fff; border:1px solid #e1e4e8; border-left:4px solid #1a73e8; border-radius:4px; padding:16px; margin-bottom:16px;">
<div style="font-size:0.84rem; line-height:1.8; color:#333;">{'<br>'.join(lines)}</div>
</div>""", unsafe_allow_html=True)

    # Top 5 Priority News - Card Style (참고 이미지 기반)
    st.markdown('<div class="section-title">실시간 분석 인사이트</div>', unsafe_allow_html=True)
    if articles:
        cols = st.columns(2)
        for rank, art in enumerate(articles[:4], 1):
            with cols[(rank-1) % 2]:
                opp = art.get("opportunity_type", "other")
                label_map = {"sales_opportunity":"영업 기회","lead_generation":"신규 리드","customer_signal":"고객 신호","proposal_evidence":"규제/정책","competitive_intelligence":"경쟁사","competitor_signal":"경쟁사","market_trend":"기술 트렌드","security_risk":"보안 리스크","cloud_migration":"클라우드","genai_opportunity":"GenAI"}
                type_label = label_map.get(opp, "기타")
                score = art.get("final_score_100", 0)
                source = art.get("source_name", "")
                title = art.get("title", "")
                reasoning = art.get("summary_ko", art.get("snippet","")[:150])
                action = art.get("suggested_action", "")

                st.markdown(f"""<div style="border:1px solid #e1e4e8; border-radius:8px; padding:16px; margin-bottom:12px; background:#fff;">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
<div><span style="background:#e8f0fe; color:#1a73e8; padding:2px 8px; border-radius:3px; font-size:0.75rem; font-weight:600;">{source}</span>
<span style="background:#f0f0f0; color:#333; padding:2px 8px; border-radius:3px; font-size:0.75rem; margin-left:4px;">{type_label}</span></div>
<div style="text-align:right;"><span style="font-size:0.65rem; color:#666; text-transform:uppercase;">LEAD SCORE</span><br>
<span style="font-size:1.6rem; font-weight:800; color:#1a73e8;">{score}</span></div>
</div>
<div style="font-size:0.95rem; font-weight:600; margin-bottom:8px; line-height:1.4;">"{title}"</div>
<div style="background:#f8f9fa; border-radius:4px; padding:10px; margin-bottom:8px;">
<div style="font-size:0.7rem; font-weight:600; color:#666; margin-bottom:4px;">AI 제안 논리 (REASONING)</div>
<div style="font-size:0.82rem; color:#333; line-height:1.5;">{reasoning}</div>
</div>
<div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#666;">
<a href="{art.get('url','#')}" target="_blank" style="color:#1a73e8; text-decoration:none;">원문 기사</a>
<span>감성: {art.get('sentiment','neutral')} | 매칭: {art.get('role_keyword_match_score',0):.2f}</span>
</div>
</div>""", unsafe_allow_html=True)

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
            if "source_name" in rx_df.columns and "source_reaction_score" in rx_df.columns:
                # trend_analyzer returns 'label' not 'reaction_label'
                color_col = "reaction_label" if "reaction_label" in rx_df.columns else "label"
                fig = px.bar(rx_df, x="source_reaction_score", y="source_name", orientation="h", color=color_col,
                    color_discrete_map={"HOT":"#dc2626","HOT RISK":"#7f1d1d","WARM":"#ea580c","COLD":"#2563eb"}, title="Source Reaction")
                fig.update_layout(height=250, margin=dict(l=0,r=0,t=30,b=0))
                st.plotly_chart(fig, use_container_width=True)

    # ─── 4. DOCUMENT EDITOR (목적별 초안 생성) ───
    st.markdown('<div class="section-title">DOCUMENT EDITOR</div>', unsafe_allow_html=True)

    # 목적별 초안 설명
    purpose_id = st.session_state["purpose_id"]
    purpose_draft_info = {
        "lead_generation": {"title": "콜드 메일 초안", "desc": "투자 유치/사업 확장 기사를 근거로 한 아웃바운드 메일 초안 생성", "icon": "OUTBOUND MAIL"},
        "proposal_support": {"title": "제안서 섹션 초안", "desc": "규제 완화/시장 변화 기사를 근거로 한 도입 배경 및 명분 섹션 초안 생성", "icon": "PROPOSAL DRAFT"},
        "competitive_intelligence": {"title": "경쟁 분석 보고서", "desc": "경쟁사 수주/파트너십 기사를 기반으로 한 경영진 보고용 경쟁 분석 초안", "icon": "COMPETITIVE REPORT"},
        "custom_search": {"title": "종합 브리핑", "desc": "검색 키워드 기반 종합 분석 브리핑 초안", "icon": "BRIEFING"},
    }
    draft_info = purpose_draft_info.get(purpose_id, purpose_draft_info["custom_search"])

    st.markdown(f"""<div style="background:#f0f7ff; border:1px solid #b8d4f0; border-radius:6px; padding:12px 16px; margin-bottom:12px;">
<span style="background:#1a73e8; color:#fff; padding:2px 8px; border-radius:3px; font-size:0.7rem; font-weight:600;">{draft_info['icon']}</span>
<span style="font-size:0.85rem; margin-left:8px; color:#333;">{draft_info['desc']}</span>
</div>""", unsafe_allow_html=True)

    ed_left, ed_right = st.columns(2)

    with ed_left:
        st.markdown(f"""<div style="background:#fff; border:1px solid #e1e4e8; border-radius:6px; padding:16px;">
<div style="font-size:0.75rem; font-weight:600; color:#666; margin-bottom:8px; text-transform:uppercase;">참조 자산 (V1) - 관련 기사 원문</div>
</div>""", unsafe_allow_html=True)
        ref_text = "\n\n---\n\n".join([f"[{a.get('source_name','')}] {a.get('title','')}\n{a.get('snippet','')[:250]}" for a in articles[:5]])
        st.text_area("ref", ref_text, height=300, key="ref_v1", label_visibility="collapsed")

    with ed_right:
        st.markdown(f"""<div style="background:#f6fef9; border:1px solid #34a853; border-radius:6px; padding:16px;">
<div style="font-size:0.75rem; font-weight:600; color:#1e7e34; margin-bottom:8px; text-transform:uppercase;">AI 생성 초안 (V+) - {draft_info['title']}</div>
</div>""", unsafe_allow_html=True)

        if "draft_text" not in st.session_state:
            st.session_state["draft_text"] = ""

        if st.button(f"{draft_info['title']} 생성", type="primary", use_container_width=True):
            with st.spinner("Bedrock 초안 작성 중..."):
                # 목적별 프롬프트 분기
                from services.bedrock_client import invoke_model
                top_art = articles[0] if articles else {}
                if purpose_id == "lead_generation":
                    prompt = f"""메가존클라우드 영업 담당자가 보낼 콜드 메일 초안을 작성하세요.

근거 기사: {top_art.get('title','')}
기사 요약: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}

형식:
- 제목: [고객사명] 투자 유치 축하 및 클라우드 인프라 확장 제안
- 본문: 축하 인사 → 기사 언급 → 인프라 확장 시 MZC가 도울 수 있는 점 → 미팅 제안
- 톤: 전문적이면서 친근하게
- 한국어로 작성"""
                elif purpose_id == "proposal_support":
                    prompt = f"""메가존클라우드 프리세일즈가 제안서에 넣을 '도입 배경 및 명분' 섹션 초안을 작성하세요.

근거 기사: {top_art.get('title','')}
기사 요약: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}

형식:
- 섹션 제목: 도입 배경
- 시장 환경 변화 (기사 근거)
- 규제/정책 변화가 고객에게 미치는 영향
- 클라우드 도입의 필요성과 기대효과
- MZC 솔루션 연결 포인트
- 한국어로 작성"""
                elif purpose_id == "competitive_intelligence":
                    prompt = f"""경영진에게 보고할 경쟁사 동향 분석 보고서 초안을 작성하세요.

근거 기사: {top_art.get('title','')}
기사 요약: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}

형식:
- 경쟁사 동향 요약
- MZC에 미치는 영향
- 차별화 포인트
- Win-back 또는 방어 전략 제안
- 한국어로 작성"""
                else:
                    prompt = f"""아래 기사를 기반으로 종합 브리핑 초안을 작성하세요.
기사: {top_art.get('title','')}
요약: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}
한국어로 작성."""

                try:
                    draft = invoke_model(prompt, max_tokens=2000)
                except Exception as e:
                    draft = f"초안 생성 실패: {e}"

                st.session_state["draft_text"] = draft
                stats = {"total_collected":len(articles),"after_dedup":len(articles),"analyzed":len(articles),"high_importance":sum(1 for a in articles if a.get("importance",0)>=8),"avg_purpose_fit":0.7}
                st.session_state["briefing_html"] = render_briefing_html(st.session_state["selected_role"], st.session_state["selected_purpose"], draft, articles[:10], stats)
                st.rerun()

        draft = st.text_area("draft", st.session_state["draft_text"], height=300, key="draft_v_plus", label_visibility="collapsed")
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
