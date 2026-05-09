"""
app.py - Agent Argos (Production UI)
?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€?€
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

st.set_page_config(page_title="Agent Argos", page_icon=None, layout="wide", initial_sidebar_state="collapsed")

# ?€?€?€ CSS ?€?€?€
st.markdown("""<style>
[data-testid="stAppViewContainer"] { background: #f5f7fa; }
.block-container { padding-top: 1rem; max-width: 1200px; }
.section-title { font-size:0.9rem; font-weight:700; color:#1a1a1a; margin:20px 0 12px 0; padding-bottom:6px; border-bottom:2px solid #e1e4e8; }
.metric-box { background:#fff; border:1px solid #e1e4e8; border-radius:6px; padding:12px 16px; }
.metric-box .val { font-size:1.5rem; font-weight:700; color:#1a73e8; }
.metric-box .lbl { font-size:0.72rem; color:#5f6368; text-transform:uppercase; }
[data-testid="stMetric"] { background:#fff; border:1px solid #e8eaed; border-radius:6px; padding:8px 12px; }
</style>""", unsafe_allow_html=True)

# ?€?€?€ Session State Init ?€?€?€
defaults = {"phase": "landing", "keyword_pool": list(DEFAULT_KEYWORDS), "search_keywords": [], "header_expanded": True, "alert_settings": {}}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•??# 1. LANDING PAGE
# ?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•??if st.session_state["phase"] == "landing":
    st.markdown("## Agent Argos")
    st.caption("ë©”ê?ì¡´í´?¼ìš°???ì—… ë°??„ë¦¬?¸ì¼ì¦ˆë? ?„í•œ ?´ìŠ¤ ê¸°ë°˜ ?ì—… ?¸í…”ë¦¬ì „??)
    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        persona = st.selectbox("ì§êµ° ? íƒ", list(ROLES.keys()), index=0)
        purpose_sel = st.selectbox("ë¶„ì„ ëª©ì ", list(PURPOSES.keys()), index=0)
    with col2:
        kw_input = st.text_input("?¤ì›Œ???…ë ¥ (?¼í‘œ êµ¬ë¶„)", placeholder="AWS, ?ì„±??AI, ê¸ˆìœµ ?´ë¼?°ë“œ, ë³´ì•ˆ")
        period = st.radio("ì¡°íšŒ ê¸°ê°„", list(WINDOW_MAP.keys()), horizontal=True, index=0)

    if not ROLES[persona]["supported"]:
        st.warning("?„ì¬ MVP?ì„œ???ì—…ê³??„ë¦¬?¸ì¼ì¦??Œí¬?Œë¡œ?°ë§Œ ?¤í–‰?©ë‹ˆ??")

    if st.button("ë¶„ì„ ?œì‘", type="primary", disabled=not ROLES[persona]["supported"]):
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

# ?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•??# LOADING
# ?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•??if st.session_state["phase"] == "loading":
    st.markdown("### ë¶„ì„ ì§„í–‰ ì¤?..")
    progress = st.progress(0)
    kws = st.session_state["search_keywords"]
    window = st.session_state["time_window"]
    role_key = st.session_state["role_key"]
    purpose_id = st.session_state["purpose_id"]

    progress.progress(0.1, "?´ìŠ¤ ?˜ì§‘ ì¤?..")
    collect_result = collect_articles(kws, window)
    norm_result = normalize_articles(collect_result["raw_articles"])
    articles = norm_result["normalized_articles"]
    progress.progress(0.3, f"{len(articles)}ê±??˜ì§‘ ?„ë£Œ")

    progress.progress(0.4, "ì¤‘ë³µ/?¸ì´ì¦??œê±° ì¤?..")
    dedup_result = dedup_and_vectorize(articles)
    filtered = dedup_result["filtered_articles"]
    progress.progress(0.5)

    progress.progress(0.6, "Bedrock ë¶„ì„ ì¤?..")
    # ?ìœ„ 20ê°œë§Œ LLM ë¶„ì„ (?ë„ ìµœì ?? 20ê°?Ã— Haiku = ~25ì´?
    articles_to_analyze = filtered[:20]
    analyzed = analyze_articles(articles_to_analyze, st.session_state["selected_role"], purpose_id)
    # ?˜ë¨¸ì§€??ë¶„ì„ ?†ì´ ê¸°ë³¸ê°’ìœ¼ë¡?ì¶”ê?
    for art in filtered[20:]:
        art.update({"importance": 3, "sentiment": "neutral", "opportunity_type": "other", "relevance_to_mzc": 0.3, "purpose_fit": 0.3, "summary_ko": art.get("snippet","")[:100], "why_it_matters": "", "suggested_action": "", "target_role": "both"})
        analyzed.append(art)
    progress.progress(0.7)

    progress.progress(0.8, "?¤ì½”?´ë§ ì¤?..")
    # ?´ìœ : Embedding ?¸ì¶œ??ìµœì†Œ?? user intent 1ë²ˆë§Œ ?¸ì¶œ?˜ê³  ê¸°ì‚¬???ˆëŠ” ê²ƒë§Œ ?¬ìš©.
    user_intent = build_user_intent_text(role_key, purpose_id, kws, [])
    try:
        user_vector = np.array(get_embedding(user_intent), dtype=np.float32)
    except Exception:
        user_vector = None

    opp_counts = Counter(a.get("opportunity_type", "other") for a in analyzed)
    max_cluster = max(opp_counts.values()) if opp_counts else 1

    for art in analyzed:
        # role_keyword_match: embedding ?ˆìœ¼ë©?cosine, ?†ìœ¼ë©??¤ì›Œ??ê²¹ì¹¨ ë¹„ìœ¨
        if user_vector is not None and "embedding" in art and art["embedding"]:
            art_vector = np.array(art["embedding"], dtype=np.float32)
            rk = calculate_role_keyword_match_score(user_vector, art_vector)
        else:
            # fallback: ?¤ì›Œ???¬í•¨ ë¹„ìœ¨ë¡?ê°„ì´ ë§¤ì¹­
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
    progress.progress(0.9, "?¸ë Œ???¬ë¡  ë¶„ì„ ì¤?..")
    trends = extract_trend_keywords(analyzed)
    sentiment_ov = calculate_sentiment_overview(analyzed)
    source_rx = calculate_source_reactions(analyzed)

    st.session_state.update({
        "articles": analyzed, "trends": trends, "sentiment_overview": sentiment_ov,
        "source_reactions": source_rx, "collect_result": collect_result,
        "dedup_result": dedup_result, "phase": "dashboard", "last_analysis": datetime.now().strftime("%H:%M"),
    })
    progress.progress(1.0, "?„ë£Œ")
    st.rerun()

# ?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•??# 2-5. DASHBOARD
# ?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•?â•??if st.session_state["phase"] == "dashboard":
    articles = st.session_state["articles"]
    trends = st.session_state["trends"]
    sentiment_ov = st.session_state["sentiment_overview"]
    source_rx = st.session_state["source_reactions"]

    # ?€?€?€ 2. STICKY HEADER ?€?€?€
    with st.container():
        hcol1, hcol2 = st.columns([10, 1])
        with hcol1:
            summary = f"{st.session_state['selected_role']} | {st.session_state['selected_purpose']} | {len(articles)}ê±?ë¶„ì„ | {st.session_state.get('last_analysis','')}"
            if not st.session_state["header_expanded"]:
                st.caption(summary)
            else:
                st.markdown(f"**{summary}**")
        with hcol2:
            if st.button("?‘ê¸°" if st.session_state["header_expanded"] else "?¼ì¹˜ê¸?, key="toggle_hdr"):
                st.session_state["header_expanded"] = not st.session_state["header_expanded"]
                st.rerun()

        if st.session_state["header_expanded"]:
            fc1, fc2, fc3 = st.columns([2, 4, 2])
            with fc1:
                new_role = st.selectbox("ì§êµ°", [r for r in ROLES if ROLES[r]["supported"]], index=0, key="hdr_role")
                new_purpose = st.selectbox("ëª©ì ", list(PURPOSES.keys()), index=0, key="hdr_purpose")
            with fc2:
                # Keyword chips
                active_kws = st.multiselect("?œì„± ?¤ì›Œ??, st.session_state["keyword_pool"], default=st.session_state["search_keywords"], key="hdr_kws")
                if st.button("AI ì¶”ì²œ ?¤ì›Œ???ì„±"):
                    with st.spinner("ì¶”ì²œ ì¤?.."):
                        r = recommend_keywords(active_kws[:5], new_role, PURPOSES[new_purpose]["id"])
                        for kw in r.get("recommended_keywords", []):
                            if kw not in st.session_state["keyword_pool"]:
                                st.session_state["keyword_pool"].append(kw)
                        st.rerun()
            with fc3:
                if st.button("ì¡°ê±´ ?ìš© ë°??¬ë¶„??, type="primary"):
                    st.session_state.update({
                        "selected_role": new_role, "role_key": ROLES[new_role]["target_role"],
                        "selected_purpose": new_purpose, "purpose_id": PURPOSES[new_purpose]["id"],
                        "search_keywords": active_kws, "phase": "loading",
                    })
                    st.rerun()
            st.markdown("---")

    # ?€?€?€ 3. SUMMARY DASHBOARD ?€?€?€
    # KPI
    cr = st.session_state["collect_result"]
    dr = st.session_state["dedup_result"]
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("?˜ì§‘", cr["total_count"])
    m2.metric("ì¤‘ë³µ ?œê±°", dr["duplicate_count"])
    m3.metric("?¸ì´ì¦??œê±°", dr["noise_count"])
    m4.metric("ë¶„ì„ ?„ë£Œ", len(articles))
    m5.metric("ì¤‘ìš”??8+", sum(1 for a in articles if a.get("importance",0)>=8))
    m6.metric("?‰ê·  ë§¤ì¹­??, f"{np.mean([a.get('role_keyword_match_score',0) for a in articles]):.2f}" if articles else "0")

    # Insight Summary - ?¤ì œ ?°ì´??ê¸°ë°˜ ì¢…í•© ë¶„ì„
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

        opp_labels = {"sales_opportunity":"?ì—… ê¸°íšŒ","lead_generation":"? ê·œ ë¦¬ë“œ/?¬ì ? í˜¸","customer_signal":"ê³ ê° IT ?¬ì ? í˜¸","proposal_evidence":"ê·œì œ/?•ì±… ë³€??,"competitive_intelligence":"ê²½ìŸ???™í–¥","competitor_signal":"ê²½ìŸ???˜ì£¼/MOU","market_trend":"ê¸°ìˆ  ?¸ë Œ??,"security_risk":"ë³´ì•ˆ ë¦¬ìŠ¤???¥ì• ","cloud_migration":"?´ë¼?°ë“œ ?„í™˜","genai_opportunity":"?ì„±??AI ê¸°íšŒ","other":"ê¸°í?"}

        # ??ì¤??”ì•½
        top_opp_label = opp_labels.get(top_opps[0][0], "ê¸°í?") if top_opps else "ê¸°í?"
        sentiment_word = "ë¶€??ë¦¬ìŠ¤???°ì„¸" if neg_count > pos_count else ("ê¸ì • ? í˜¸ ?°ì„¸" if pos_count > neg_count else "ì¤‘ë¦½ ?¼ì¬")
        one_liner = f"{len(articles)}ê±?ë¶„ì„ ê²°ê³¼, '{top_opp_label}' ? í˜•??ê°€??ë§ê³  ?¬ë¡ ?€ {sentiment_word}?…ë‹ˆ?? ?‰ê·  ?„íŒ©??{avg_score:.0f}??"
        st.markdown(f"""<div style="font-size:0.95rem; font-weight:600; color:#1a73e8; margin-bottom:8px;">{one_liner}</div>""", unsafe_allow_html=True)

        # ?¤ì œ ë¶„ì„ ?ìŠ¤??êµ¬ì„±
        lines = []
        lines.append(f"<b>[ë¶„ì„ ë²”ìœ„]</b> {len(articles)}ê±?ê¸°ì‚¬ ë¶„ì„ ?„ë£Œ. ?‰ê·  ?„íŒ©???¤ì½”??{avg_score:.1f}?? ì¤‘ìš”??7+ ê¸°ì‚¬ {len(high_imp)}ê±?ê°ì?.")
        if hot_kws:
            lines.append(f"<b>[?µì‹¬ ?¤ì›Œ??</b> ê°€??ë§ì´ ?¸ê¸‰???¤ì›Œ?? {', '.join(f'{k}({v}ê±?' for k,v in hot_kws)}.")
        lines.append(f"<b>[ê¸°íšŒ ? í˜•]</b> ?ìœ„ ê¸°íšŒ: {', '.join(f'{opp_labels.get(o[0],o[0])}({o[1]}ê±?' for o in top_opps)}.")
        lines.append(f"<b>[?¬ë¡  ?™í–¥]</b> ê¸ì • {pos_count}ê±?/ ì¤‘ë¦½ {neu_count}ê±?/ ë¶€??{neg_count}ê±? {'ë¶€??ê¸°ì‚¬ê°€ ë§ì•„ ë¦¬ìŠ¤???€???°ì„ .' if neg_count > pos_count else 'ê¸ì • ?°ì„¸ë¡??œì¥ ?•ì¥ ê¸°íšŒ ?œìš© ê°€??'}")
        lines.append(f"<b>[ë§¤ì²´ ë¶„í¬]</b> ì£¼ìš” ë³´ë„: {', '.join(f'{s[0]}({s[1]}ê±?' for s in top_sources)}.")
        if articles[0].get("why_it_matters"):
            lines.append(f"<b>[ìµœìš°??ê¸°ì‚¬ ?œì‚¬??</b> {articles[0]['why_it_matters']}")
        if articles[0].get("suggested_action"):
            lines.append(f"<b>[ê¶Œì¥ ?¡ì…˜]</b> {articles[0]['suggested_action']}")

        st.markdown(f"""<div style="background:#fff; border:1px solid #e1e4e8; border-left:4px solid #1a73e8; border-radius:4px; padding:16px; margin-bottom:16px;">
<div style="font-size:0.84rem; line-height:1.8; color:#333;">{'<br>'.join(lines)}</div>
</div>""", unsafe_allow_html=True)

    # Top 5 Priority News - Card Style (ì°¸ê³  ?´ë?ì§€ ê¸°ë°˜)
    st.markdown('<div class="section-title">?¤ì‹œê°?ë¶„ì„ ?¸ì‚¬?´íŠ¸</div>', unsafe_allow_html=True)
    if articles:
        cols = st.columns(2)
        for rank, art in enumerate(articles[:4], 1):
            with cols[(rank-1) % 2]:
                opp = art.get("opportunity_type", "other")
                label_map = {"sales_opportunity":"?ì—… ê¸°íšŒ","lead_generation":"? ê·œ ë¦¬ë“œ","customer_signal":"ê³ ê° ? í˜¸","proposal_evidence":"ê·œì œ/?•ì±…","competitive_intelligence":"ê²½ìŸ??,"competitor_signal":"ê²½ìŸ??,"market_trend":"ê¸°ìˆ  ?¸ë Œ??,"security_risk":"ë³´ì•ˆ ë¦¬ìŠ¤??,"cloud_migration":"?´ë¼?°ë“œ","genai_opportunity":"GenAI"}
                type_label = label_map.get(opp, "ê¸°í?")
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
<div style="font-size:0.7rem; font-weight:600; color:#666; margin-bottom:4px;">AI ?œì•ˆ ?¼ë¦¬ (REASONING)</div>
<div style="font-size:0.82rem; color:#333; line-height:1.5;">{reasoning}</div>
</div>
<div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#666;">
<a href="{art.get('url','#')}" target="_blank" style="color:#1a73e8; text-decoration:none;">?ë¬¸ ê¸°ì‚¬</a>
<span>ê°ì„±: {art.get('sentiment','neutral')} | ë§¤ì¹­: {art.get('role_keyword_match_score',0):.2f}</span>
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

    # ?€?€?€ 4. DOCUMENT EDITOR (ëª©ì ë³?ì´ˆì•ˆ ?ì„±) ?€?€?€
    st.markdown('<div class="section-title">DOCUMENT EDITOR</div>', unsafe_allow_html=True)

    # ëª©ì ë³?ì´ˆì•ˆ ?¤ëª…
    purpose_id = st.session_state["purpose_id"]
    purpose_draft_info = {
        "lead_generation": {"title": "ì½œë“œ ë©”ì¼ ì´ˆì•ˆ", "desc": "?¬ì ? ì¹˜/?¬ì—… ?•ì¥ ê¸°ì‚¬ë¥?ê·¼ê±°ë¡????„ì›ƒë°”ìš´??ë©”ì¼ ì´ˆì•ˆ ?ì„±", "icon": "OUTBOUND MAIL"},
        "proposal_support": {"title": "?œì•ˆ???¹ì…˜ ì´ˆì•ˆ", "desc": "ê·œì œ ?„í™”/?œì¥ ë³€??ê¸°ì‚¬ë¥?ê·¼ê±°ë¡????„ì… ë°°ê²½ ë°?ëª…ë¶„ ?¹ì…˜ ì´ˆì•ˆ ?ì„±", "icon": "PROPOSAL DRAFT"},
        "competitive_intelligence": {"title": "ê²½ìŸ ë¶„ì„ ë³´ê³ ??, "desc": "ê²½ìŸ???˜ì£¼/?ŒíŠ¸?ˆì‹­ ê¸°ì‚¬ë¥?ê¸°ë°˜?¼ë¡œ ??ê²½ì˜ì§?ë³´ê³ ??ê²½ìŸ ë¶„ì„ ì´ˆì•ˆ", "icon": "COMPETITIVE REPORT"},
        "custom_search": {"title": "ì¢…í•© ë¸Œë¦¬??, "desc": "ê²€???¤ì›Œ??ê¸°ë°˜ ì¢…í•© ë¶„ì„ ë¸Œë¦¬??ì´ˆì•ˆ", "icon": "BRIEFING"},
    }
    draft_info = purpose_draft_info.get(purpose_id, purpose_draft_info["custom_search"])

    st.markdown(f"""<div style="background:#f0f7ff; border:1px solid #b8d4f0; border-radius:6px; padding:12px 16px; margin-bottom:12px;">
<span style="background:#1a73e8; color:#fff; padding:2px 8px; border-radius:3px; font-size:0.7rem; font-weight:600;">{draft_info['icon']}</span>
<span style="font-size:0.85rem; margin-left:8px; color:#333;">{draft_info['desc']}</span>
</div>""", unsafe_allow_html=True)

    ed_left, ed_right = st.columns(2)

    with ed_left:
        st.markdown(f"""<div style="background:#fff; border:1px solid #e1e4e8; border-radius:6px; padding:16px;">
<div style="font-size:0.75rem; font-weight:600; color:#666; margin-bottom:8px; text-transform:uppercase;">ì°¸ì¡° ?ì‚° (V1) - ê´€??ê¸°ì‚¬ ?ë¬¸</div>
</div>""", unsafe_allow_html=True)
        ref_text = "\n\n---\n\n".join([f"[{a.get('source_name','')}] {a.get('title','')}\n{a.get('snippet','')[:250]}" for a in articles[:5]])
        st.text_area("ref", ref_text, height=300, key="ref_v1", label_visibility="collapsed")

    with ed_right:
        st.markdown(f"""<div style="background:#f6fef9; border:1px solid #34a853; border-radius:6px; padding:16px;">
<div style="font-size:0.75rem; font-weight:600; color:#1e7e34; margin-bottom:8px; text-transform:uppercase;">AI ?ì„± ì´ˆì•ˆ (V+) - {draft_info['title']}</div>
</div>""", unsafe_allow_html=True)

        if "draft_text" not in st.session_state:
            st.session_state["draft_text"] = ""

        if st.button(f"{draft_info['title']} ?ì„±", type="primary", use_container_width=True):
            with st.spinner("Bedrock ì´ˆì•ˆ ?‘ì„± ì¤?.."):
                # ëª©ì ë³??„ë¡¬?„íŠ¸ ë¶„ê¸°
                from services.bedrock_client import invoke_model
                top_art = articles[0] if articles else {}
                if purpose_id == "lead_generation":
                    prompt = f"""ë©”ê?ì¡´í´?¼ìš°???ì—… ?´ë‹¹?ê? ë³´ë‚¼ ì½œë“œ ë©”ì¼ ì´ˆì•ˆ???‘ì„±?˜ì„¸??

ê·¼ê±° ê¸°ì‚¬: {top_art.get('title','')}
ê¸°ì‚¬ ?”ì•½: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}

?•ì‹:
- ?œëª©: [ê³ ê°?¬ëª…] ?¬ì ? ì¹˜ ì¶•í•˜ ë°??´ë¼?°ë“œ ?¸í”„???•ì¥ ?œì•ˆ
- ë³¸ë¬¸: ì¶•í•˜ ?¸ì‚¬ ??ê¸°ì‚¬ ?¸ê¸‰ ???¸í”„???•ì¥ ??MZCê°€ ?„ìš¸ ???ˆëŠ” ????ë¯¸íŒ… ?œì•ˆ
- ?? ?„ë¬¸?ì´ë©´ì„œ ì¹œê·¼?˜ê²Œ
- ?œêµ­?´ë¡œ ?‘ì„±"""
                elif purpose_id == "proposal_support":
                    prompt = f"""ë©”ê?ì¡´í´?¼ìš°???„ë¦¬?¸ì¼ì¦ˆê? ?œì•ˆ?œì— ?£ì„ '?„ì… ë°°ê²½ ë°?ëª…ë¶„' ?¹ì…˜ ì´ˆì•ˆ???‘ì„±?˜ì„¸??

ê·¼ê±° ê¸°ì‚¬: {top_art.get('title','')}
ê¸°ì‚¬ ?”ì•½: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}

?•ì‹:
- ?¹ì…˜ ?œëª©: ?„ì… ë°°ê²½
- ?œì¥ ?˜ê²½ ë³€??(ê¸°ì‚¬ ê·¼ê±°)
- ê·œì œ/?•ì±… ë³€?”ê? ê³ ê°?ê²Œ ë¯¸ì¹˜???í–¥
- ?´ë¼?°ë“œ ?„ì…???„ìš”?±ê³¼ ê¸°ë??¨ê³¼
- MZC ?”ë£¨???°ê²° ?¬ì¸??- ?œêµ­?´ë¡œ ?‘ì„±"""
                elif purpose_id == "competitive_intelligence":
                    prompt = f"""ê²½ì˜ì§„ì—ê²?ë³´ê³ ??ê²½ìŸ???™í–¥ ë¶„ì„ ë³´ê³ ??ì´ˆì•ˆ???‘ì„±?˜ì„¸??

ê·¼ê±° ê¸°ì‚¬: {top_art.get('title','')}
ê¸°ì‚¬ ?”ì•½: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}

?•ì‹:
- ê²½ìŸ???™í–¥ ?”ì•½
- MZC??ë¯¸ì¹˜???í–¥
- ì°¨ë³„???¬ì¸??- Win-back ?ëŠ” ë°©ì–´ ?„ëµ ?œì•ˆ
- ?œêµ­?´ë¡œ ?‘ì„±"""
                else:
                    prompt = f"""?„ë˜ ê¸°ì‚¬ë¥?ê¸°ë°˜?¼ë¡œ ì¢…í•© ë¸Œë¦¬??ì´ˆì•ˆ???‘ì„±?˜ì„¸??
ê¸°ì‚¬: {top_art.get('title','')}
?”ì•½: {top_art.get('summary_ko', top_art.get('snippet','')[:200])}
?œêµ­?´ë¡œ ?‘ì„±."""

                try:
                    draft = invoke_model(prompt, max_tokens=2000)
                except Exception as e:
                    draft = f"ì´ˆì•ˆ ?ì„± ?¤íŒ¨: {e}"

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
            st.download_button("HTML ?¤ìš´ë¡œë“œ", st.session_state["briefing_html"], "briefing.html", "text/html", use_container_width=True)
    with act2:
        if st.button("Google Docs ?´ë³´?´ê¸°", use_container_width=True):
            st.info("Google Docs export???´ì˜ ?°ë™ ?€?ì…?ˆë‹¤. ?„ì¬??HTML ?¤ìš´ë¡œë“œë¥??œê³µ?©ë‹ˆ??")
    with act3:
        if "briefing_html" in st.session_state:
            st.download_button("DOCX", f"<html><head><meta charset='utf-8'></head><body>{st.session_state['briefing_html']}</body></html>".encode(), "briefing.doc", "application/msword", use_container_width=True)
    with act4:
        if st.button("?„í‚¤?ì²˜ ë¬¸ì„œ ?ì„±", use_container_width=True):
            with st.spinner("?ì„± ì¤?.."):
                from agents.architecture_doc import generate_architecture_doc
                st.session_state["arch_html"] = generate_architecture_doc()
                st.rerun()
    with act5:
        pass  # Slack alert button below

    if "arch_html" in st.session_state:
        with st.expander("?„í‚¤?ì²˜ ë¬¸ì„œ ë¯¸ë¦¬ë³´ê¸°"):
            st.components.v1.html(st.session_state["arch_html"], height=400, scrolling=True)
            st.download_button("?„í‚¤?ì²˜ HTML ?¤ìš´ë¡œë“œ", st.session_state["arch_html"], "architecture.html", "text/html")

    # ?€?€?€ 5. SLACK ALERT SETTINGS ?€?€?€
    st.markdown('<div class="section-title">ALERT SETTINGS</div>', unsafe_allow_html=True)
    with st.expander("Slack Alert ?¤ì •"):
        al1, al2 = st.columns(2)
        with al1:
            st.markdown("**?•ê¸° ?”ì•½ ë³´ê³ **")
            sched_enabled = st.checkbox("?œì„±??, key="sched_on", value=st.session_state["alert_settings"].get("scheduled", False))
            sched_time = st.time_input("ë°œì†¡ ?œê°", value=datetime.strptime("08:00", "%H:%M").time(), key="sched_time")
        with al2:
            st.markdown("**?µì‹¬ ?´ìŠˆ ?¤ì‹œê°??Œë¦¼**")
            rt_enabled = st.checkbox("?œì„±??, key="rt_on", value=st.session_state["alert_settings"].get("realtime", False))
            threshold = st.slider("?„íŒ©???¤ì½”???„ê³„ì¹?, 50, 100, 85, key="rt_threshold")
            alert_count = sum(1 for a in articles if a.get("final_score_100",0) >= threshold)
            st.caption(f"?„ì¬ ì¡°ê±´?ì„œ ?Œë¦¼ ?€?? {alert_count}ê±?)

        st.markdown("**ëª¨ë‹ˆ?°ë§ ê¸°ê°„**")
        mon_type = st.radio("? í˜•", ["?ì‹œ ëª¨ë‹ˆ?°ë§", "?„ë¡œ?íŠ¸ ê¸°ë°˜"], horizontal=True, key="mon_type")
        if mon_type == "?„ë¡œ?íŠ¸ ê¸°ë°˜":
            mon_dates = st.date_input("ê¸°ê°„", value=(datetime.now().date(), datetime.now().date()), key="mon_dates")

        st.caption("?°ê²°: MegazoneCloud Slack Workspace / #sales-radar-alerts")

        if st.button("?Œë¦¼ ?¤ì • ?€??):
            st.session_state["alert_settings"] = {
                "scheduled": sched_enabled, "schedule_time": str(sched_time),
                "realtime": rt_enabled, "threshold": threshold,
                "monitoring": mon_type,
            }
            st.success("?Œë¦¼ ?¤ì •???€?¥ë˜?ˆìŠµ?ˆë‹¤.")

    # ?€?€?€ Footer ?€?€?€
    st.markdown("---")
    if st.button("ì²˜ìŒ?¼ë¡œ"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.rerun()

