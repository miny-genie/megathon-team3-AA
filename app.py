import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamlit as st
import pandas as pd
import plotly.express as px
from config import ROLES, PURPOSES, DEFAULT_KEYWORDS, WINDOW_MAP
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
    calculate_hotness_score, calculate_final_score, build_score_reason
)
from services.trend_analyzer import extract_trend_keywords, calculate_sentiment_overview, calculate_source_reactions
from services.bedrock_client import get_embedding

st.set_page_config(page_title='MZC Sales Radar', page_icon='📡', layout='wide')

# --- Session State Init ---
for key in ['search_result', 'normalized', 'briefing', 'scoring_done', 'scored_articles',
            'trends', 'sentiment_overview', 'source_reactions', 'keyword_pool', 'search_keywords']:
    if key not in st.session_state:
        st.session_state[key] = None
if 'keyword_pool' not in st.session_state or st.session_state.keyword_pool is None:
    st.session_state.keyword_pool = list(DEFAULT_KEYWORDS)
if 'search_keywords' not in st.session_state or st.session_state.search_keywords is None:
    st.session_state.search_keywords = []
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False

# --- Header ---
h1, h2 = st.columns([8, 2])
with h1:
    st.title("📡 MZC Sales Radar")
with h2:
    st.session_state.dark_mode = st.toggle("🌙 Dark Mode", value=st.session_state.dark_mode)

# --- Export buttons ---
if st.session_state.briefing:
    ec1, ec2, ec3, ec4, _ = st.columns([1, 1, 1, 1, 6])
    with ec1:
        html_out = render_briefing_html(st.session_state.briefing)
        st.download_button("📄 HTML", html_out, "briefing.html", "text/html")
    with ec2:
        st.button("📝 DOCX", disabled=True)
    with ec3:
        st.button("📑 PDF", disabled=True)
    with ec4:
        st.button("🔗 Notion", disabled=True)

# --- Sidebar ---
with st.sidebar:
    st.header("⚙️ 설정")
    role = st.radio("역할 선택", ROLES, index=0)
    if role not in ["영업", "프리세일즈"]:
        st.warning("현재 영업/프리세일즈 역할만 지원됩니다.")

    window = st.radio("검색 기간", list(WINDOW_MAP.keys()), index=1)

    st.subheader("🔑 키워드 관리")
    if st.button("🤖 AI 키워드 추천"):
        with st.spinner("키워드 추천 중..."):
            recs = recommend_keywords(role, list(WINDOW_MAP.keys()).index(window))
            for k in recs:
                if k not in st.session_state.keyword_pool:
                    st.session_state.keyword_pool.append(k)

    new_pool = st.text_input("풀에 키워드 추가", placeholder="키워드 입력 후 Enter")
    if new_pool and new_pool not in st.session_state.keyword_pool:
        st.session_state.keyword_pool.append(new_pool)

    pool_to_search = st.multiselect("풀 → 검색에 추가", st.session_state.keyword_pool)
    if pool_to_search:
        for k in pool_to_search:
            if k not in st.session_state.search_keywords:
                st.session_state.search_keywords.append(k)

    new_search = st.text_input("검색 키워드 직접 입력", placeholder="직접 입력")
    if new_search and new_search not in st.session_state.search_keywords:
        st.session_state.search_keywords.append(new_search)

    remove_from_search = st.multiselect("검색에서 제거 (풀로 복귀)", st.session_state.search_keywords)
    if remove_from_search:
        for k in remove_from_search:
            st.session_state.search_keywords.remove(k)
            if k not in st.session_state.keyword_pool:
                st.session_state.keyword_pool.append(k)

    if st.button("🔄 키워드 초기화"):
        st.session_state.keyword_pool = list(DEFAULT_KEYWORDS)
        st.session_state.search_keywords = []
        st.rerun()

    st.caption(f"현재 검색 키워드: {st.session_state.search_keywords}")

    if st.button("🔍 검색 실행", type="primary", use_container_width=True):
        if not st.session_state.search_keywords:
            st.error("검색 키워드를 추가하세요.")
        elif role not in ["영업", "프리세일즈"]:
            st.error("영업 또는 프리세일즈 역할을 선택하세요.")
        else:
            with st.spinner("뉴스 수집 중..."):
                days = WINDOW_MAP[window]
                raw = collect_articles(st.session_state.search_keywords, days)
                normalized = normalize_articles(raw)
                st.session_state.search_result = raw
                st.session_state.normalized = normalized
                st.session_state.scoring_done = False
                st.session_state.scored_articles = None
                st.session_state.briefing = None

# --- Main Area ---
if st.session_state.normalized:
    articles = st.session_state.normalized
    df = pd.DataFrame(articles)

    tab1, tab2, tab3 = st.tabs(["📰 검색 결과", "🎯 스코어링 & 대시보드", "📊 분석 리포트"])

    # === Tab 1: Search Results ===
    with tab1:
        raw = st.session_state.search_result or []
        total = len(raw)
        norm_count = len(articles)
        sources = df['source'].nunique() if 'source' in df.columns else 0
        failed = total - norm_count

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("수집 기사", total)
        k2.metric("정규화 완료", norm_count)
        k3.metric("소스 수", sources)
        k4.metric("실패", failed)

        if not df.empty:
            c1, c2 = st.columns(2)
            with c1:
                if 'source' in df.columns:
                    fig = px.bar(df['source'].value_counts().reset_index(), x='source', y='count', title="소스별 기사 수")
                    st.plotly_chart(fig, use_container_width=True)
            with c2:
                if 'section' in df.columns:
                    fig = px.pie(df, names='section', title="섹션 분포")
                    st.plotly_chart(fig, use_container_width=True)

            c3, c4 = st.columns(2)
            with c3:
                if 'published_date' in df.columns:
                    date_df = df.groupby('published_date').size().reset_index(name='count')
                    fig = px.line(date_df, x='published_date', y='count', title="일자별 기사 수")
                    st.plotly_chart(fig, use_container_width=True)
            with c4:
                if 'source' in df.columns and 'section' in df.columns:
                    fig = px.treemap(df, path=['source', 'section'], title="소스-섹션 트리맵")
                    st.plotly_chart(fig, use_container_width=True)

            st.subheader("기사 목록")
            for i, row in df.iterrows():
                with st.expander(f"[{row.get('source','')}] {row.get('title','제목없음')}"):
                    st.write(f"**날짜:** {row.get('published_date','')}")
                    st.write(f"**요약:** {row.get('summary','')}")
                    if row.get('link'):
                        st.markdown(f"[원문 링크]({row['link']})")

    # === Tab 2: Scoring & Dashboard ===
    with tab2:
        if st.button("🎯 스코어링 분석 실행", type="primary"):
            with st.spinner("스코어링 파이프라인 실행 중... (Bedrock 호출 포함)"):
                deduped = dedup_and_vectorize(articles)
                analyzed = analyze_articles(deduped, role)
                user_intent = build_user_intent_text(role, st.session_state.search_keywords)
                user_emb = get_embedding(user_intent)

                scored = []
                for art in analyzed:
                    art_intent = build_article_intent_text(art)
                    art_emb = get_embedding(art_intent)
                    rk_score = calculate_role_keyword_match_score(art, role, st.session_state.search_keywords)
                    rec_score = calculate_recency_score(art.get('published_date', ''))
                    cluster = [a for a in analyzed if a.get('opportunity_type') == art.get('opportunity_type')]
                    hot_score = calculate_hotness_score(art, cluster)
                    src_weight = get_source_weight(art.get('source', ''))
                    final = calculate_final_score(
                        art, user_emb, art_emb, rk_score, rec_score, hot_score, src_weight
                    )
                    art['final_score'] = final
                    art['final_score_100'] = round(final * 100, 1)
                    art['role_keyword_score'] = rk_score
                    art['recency_score'] = rec_score
                    art['hotness_score'] = hot_score
                    art['source_weight'] = src_weight
                    art['score_reason'] = build_score_reason(art, role, st.session_state.search_keywords)
                    scored.append(art)

                scored.sort(key=lambda x: x['final_score'], reverse=True)
                trends = extract_trend_keywords(scored)
                sentiment_ov = calculate_sentiment_overview(scored)
                source_rx = calculate_source_reactions(scored)

                st.session_state.scored_articles = scored
                st.session_state.trends = trends
                st.session_state.sentiment_overview = sentiment_ov
                st.session_state.source_reactions = source_rx
                st.session_state.scoring_done = True

        if st.session_state.scoring_done and st.session_state.scored_articles:
            scored = st.session_state.scored_articles
            trends = st.session_state.trends
            sentiment_ov = st.session_state.sentiment_overview
            source_rx = st.session_state.source_reactions

            # A) Top 5 Priority News
            st.subheader("🏆 Top 5 Priority News")
            for rank, art in enumerate(scored[:5], 1):
                with st.container():
                    left, right = st.columns([7, 3])
                    with left:
                        st.markdown(f"### #{rank} {art.get('title','')}")
                        st.caption(f"{art.get('source','')} | {art.get('published_date','')}")
                        with st.expander("스코어 상세"):
                            sc1, sc2, sc3, sc4 = st.columns(4)
                            sc1.metric("LLM 중요도", f"{art.get('importance_score', 0):.1f}")
                            sc2.metric("MZC 관련성", f"{art.get('mzc_relevance_score', 0):.1f}")
                            sc3.metric("목적 적합", f"{art.get('purpose_fit_score', 0):.1f}")
                            sc4.metric("역할/키워드", f"{art.get('role_keyword_score', 0):.2f}")
                            sc5, sc6, sc7, sc8 = st.columns(4)
                            sc5.metric("감성 리스크", f"{art.get('sentiment_risk_score', 0):.1f}")
                            sc6.metric("최신성", f"{art.get('recency_score', 0):.2f}")
                            sc7.metric("핫니스", f"{art.get('hotness_score', 0):.2f}")
                            sc8.metric("소스 가중치", f"{art.get('source_weight', 0):.2f}")
                        st.info(f"💡 {art.get('score_reason','')}")
                        st.write(f"**요약:** {art.get('summary_ko', art.get('summary',''))}")
                        st.write(f"**Why it matters:** {art.get('why_it_matters','')}")
                        st.write(f"**Suggested Action:** {art.get('suggested_action','')}")
                        if art.get('link'):
                            st.markdown(f"[🔗 원문]({art['link']})")
                    with right:
                        st.markdown(
                            f"<div style='text-align:center;padding:20px;'>"
                            f"<span style='font-size:14px;color:gray;'>IMPACT SCORE</span><br>"
                            f"<span style='font-size:56px;font-weight:bold;color:#FF4B4B;'>{art.get('final_score_100', 0)}</span>"
                            f"</div>", unsafe_allow_html=True
                        )
                    st.divider()

            # B) Current Trends
            st.subheader("📈 Current Trends")
            if trends:
                trend_df = pd.DataFrame(trends[:10])
                if not trend_df.empty and 'keyword' in trend_df.columns:
                    fig = px.bar(trend_df, x='keyword', y='count', title="Top 10 트렌드 키워드", color='count')
                    st.plotly_chart(fig, use_container_width=True)
                    st.dataframe(trend_df, use_container_width=True)

            # C) Overall Sentiment
            st.subheader("💭 Overall Sentiment")
            if sentiment_ov:
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Sentiment Index", f"{sentiment_ov.get('sentiment_index', 0):.2f}")
                s2.metric("긍정", sentiment_ov.get('positive', 0))
                s3.metric("중립", sentiment_ov.get('neutral', 0))
                s4.metric("부정", sentiment_ov.get('negative', 0))

                pie_data = pd.DataFrame({
                    'sentiment': ['긍정', '중립', '부정'],
                    'count': [sentiment_ov.get('positive', 0), sentiment_ov.get('neutral', 0), sentiment_ov.get('negative', 0)]
                })
                fig = px.pie(pie_data, names='sentiment', values='count', title="감성 분포",
                             color='sentiment', color_discrete_map={'긍정':'green','중립':'gray','부정':'red'})
                st.plotly_chart(fig, use_container_width=True)

                tp, tn = st.columns(2)
                with tp:
                    st.markdown("**Top 3 긍정 기사**")
                    for a in sentiment_ov.get('top_positive', [])[:3]:
                        st.write(f"- {a.get('title','')}")
                with tn:
                    st.markdown("**Top 3 부정 기사**")
                    for a in sentiment_ov.get('top_negative', [])[:3]:
                        st.write(f"- {a.get('title','')}")

            # D) Source Hot/Cold Reaction
            st.subheader("🔥 Source Hot/Cold Reaction")
            if source_rx:
                rx_df = pd.DataFrame(source_rx)
                if not rx_df.empty and 'source' in rx_df.columns and 'reaction_score' in rx_df.columns:
                    color_map = {'HOT': 'red', 'HOT RISK': 'darkred', 'WARM': 'orange', 'COLD': 'blue'}
                    rx_df['color'] = rx_df.get('badge', pd.Series(['WARM']*len(rx_df))).map(
                        lambda x: color_map.get(x, 'gray'))
                    fig = px.bar(rx_df, x='source', y='reaction_score', title="소스별 반응 점수",
                                 color='badge', color_discrete_map=color_map)
                    st.plotly_chart(fig, use_container_width=True)

                    for _, row in rx_df.iterrows():
                        badge_color = color_map.get(row.get('badge',''), 'gray')
                        st.markdown(
                            f"<span style='background:{badge_color};color:white;padding:2px 8px;border-radius:4px;'>"
                            f"{row.get('badge','')}</span> **{row.get('source','')}** - "
                            f"반응점수: {row.get('reaction_score',0):.2f}", unsafe_allow_html=True)

                    if 'sentiment_pos' in rx_df.columns:
                        sent_df = rx_df[['source','sentiment_pos','sentiment_neu','sentiment_neg']].melt(
                            id_vars='source', var_name='sentiment', value_name='count')
                        fig = px.bar(sent_df, x='source', y='count', color='sentiment',
                                     title="소스별 감성 분포", barmode='stack')
                        st.plotly_chart(fig, use_container_width=True)

                    st.markdown("**소스별 대표 기사**")
                    for _, row in rx_df.iterrows():
                        if row.get('top_article'):
                            st.write(f"- [{row['source']}] {row['top_article']}")

    # === Tab 3: Analysis Report ===
    with tab3:
        purpose = st.selectbox("분석 목적 선택", PURPOSES)
        if st.button("📊 리포트 생성", type="primary"):
            with st.spinner("분석 리포트 생성 중..."):
                deduped = dedup_and_vectorize(articles)
                analyzed = analyze_articles(deduped, role)
                briefing = generate_briefing(analyzed, role, purpose)
                st.session_state.briefing = briefing

        if st.session_state.briefing:
            briefing = st.session_state.briefing
            st.subheader("📋 브리핑 결과")
            if isinstance(briefing, dict):
                st.markdown(briefing.get('executive_summary', ''))
                for item in briefing.get('items', []):
                    with st.expander(item.get('title', '항목')):
                        st.write(item.get('content', ''))
                        if item.get('action'):
                            st.success(f"💡 Action: {item['action']}")
            else:
                st.markdown(str(briefing))
else:
    st.info("👈 사이드바에서 키워드를 설정하고 검색을 실행하세요.")
