"""
app.py - MZC Sales Radar (v4)
──────────────────────────────
변경:
- 실제 검색 키워드 칸에서도 직접 입력 가능
- 검색 결과 탭에 대시보드 차트 전부 복원 (언론사별, 섹션별, 감성, 기회유형, 중요도)
"""
import sys
import os

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

# ─── 페이지 설정 ───
st.set_page_config(page_title="MZC Sales Radar", page_icon="📡", layout="wide")

# ─── 다크/라이트 모드 ───
if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = False

if st.session_state["dark_mode"]:
    st.markdown("""<style>
        .stApp { background-color: #1a1a2e; color: #e0e0e0; }
        .stSidebar > div { background-color: #16213e; }
    </style>""", unsafe_allow_html=True)

# ─── 헤더 ───
h1, h2 = st.columns([8, 2])
with h1:
    st.title("📡 MZC Sales Radar")
    st.caption("AWS Bedrock + AgentCore 기반 Multi-Agent 뉴스 인텔리전스")
with h2:
    dark = st.toggle("🌙 다크모드", value=st.session_state["dark_mode"])
    if dark != st.session_state["dark_mode"]:
        st.session_state["dark_mode"] = dark
        st.rerun()

# ─── 내보내기 (결과 있을 때만) ───
if "briefing_html" in st.session_state:
    st.markdown("---")
    exp1, exp2, exp3, exp4 = st.columns(4)
    html = st.session_state["briefing_html"]
    with exp1:
        st.download_button("📄 HTML", data=html, file_name="briefing.html", mime="text/html", use_container_width=True)
    with exp2:
        doc = f"<html><head><meta charset='utf-8'></head><body>{html}</body></html>"
        st.download_button("📝 DOCX", data=doc.encode(), file_name="briefing.doc", mime="application/msword", use_container_width=True)
    with exp3:
        pdf_html = html.replace("</head>", "<script>window.onload=function(){window.print();}</script></head>")
        st.download_button("📋 PDF", data=pdf_html, file_name="briefing_print.html", mime="text/html", use_container_width=True, help="브라우저에서 열면 인쇄→PDF 저장")
    with exp4:
        from bs4 import BeautifulSoup
        st.download_button("📒 Notion", data=BeautifulSoup(html, "html.parser").get_text("\n\n"), file_name="briefing.md", mime="text/markdown", use_container_width=True)
    st.markdown("---")

# ─── 사이드바 ───
with st.sidebar:
    st.header("⚙️ 설정")
    
    # 1. 직군
    st.subheader("1️⃣ 직군")
    selected_role = st.radio("직군", list(ROLES.keys()), horizontal=True, label_visibility="collapsed", index=0)
    if not ROLES[selected_role]["supported"]:
        st.warning("⚠️ MVP에서는 영업/프리세일즈만 지원합니다.")
        st.stop()
    
    # 2. 조회 기간
    st.subheader("2️⃣ 조회 기간")
    time_window = st.radio("기간", list(WINDOW_MAP.keys()), horizontal=True, label_visibility="collapsed", index=0)
    
    # 3. 키워드
    st.subheader("3️⃣ 키워드")
    
    if "keyword_pool" not in st.session_state:
        st.session_state["keyword_pool"] = list(DEFAULT_KEYWORDS)
    if "search_keywords" not in st.session_state:
        st.session_state["search_keywords"] = list(DEFAULT_KEYWORDS[:4])
    
    # AI 추천
    if st.button("🤖 AI 키워드 추천", use_container_width=True):
        with st.spinner("추천 중..."):
            r = recommend_keywords(st.session_state["search_keywords"][:5], selected_role, "custom_search")
            for kw in r["recommended_keywords"]:
                if kw not in st.session_state["keyword_pool"]:
                    st.session_state["keyword_pool"].append(kw)
            st.session_state["_strategy"] = r.get("search_strategy", "")
            st.rerun()
    
    if "_strategy" in st.session_state:
        st.caption(f"💡 {st.session_state['_strategy']}")
    
    # 키워드 풀에 추가
    new_pool_kw = st.text_input("키워드 풀에 추가", placeholder="입력 후 Enter", label_visibility="collapsed", key="add_pool")
    if new_pool_kw and new_pool_kw.strip():
        kw = new_pool_kw.strip()
        if kw not in st.session_state["keyword_pool"]:
            st.session_state["keyword_pool"].append(kw)
        st.rerun()
    
    # ── 키워드 풀 (후보) → 선택하면 검색으로 이동 ──
    st.caption("📦 키워드 풀 → 선택하면 검색창으로 이동")
    pool_available = [k for k in st.session_state["keyword_pool"] if k not in st.session_state["search_keywords"]]
    add_to_search = st.multiselect("풀에서 추가", options=pool_available, default=[], label_visibility="collapsed", key="pool_select")
    if add_to_search:
        for k in add_to_search:
            if k not in st.session_state["search_keywords"]:
                st.session_state["search_keywords"].append(k)
        st.rerun()
    
    # ── 실제 검색 키워드 (직접 입력도 가능) ──
    st.caption("🔍 실제 검색 키워드 (직접 입력 가능, 해제하면 풀로 돌아감)")
    
    # 이유: 검색 키워드 칸에서도 직접 입력 가능하게
    new_search_kw = st.text_input("검색 키워드 직접 추가", placeholder="검색할 키워드 입력 후 Enter", label_visibility="collapsed", key="add_search")
    if new_search_kw and new_search_kw.strip():
        kw = new_search_kw.strip()
        if kw not in st.session_state["search_keywords"]:
            st.session_state["search_keywords"].append(kw)
        if kw not in st.session_state["keyword_pool"]:
            st.session_state["keyword_pool"].append(kw)
        st.rerun()
    
    current_search = st.multiselect(
        "검색 키워드",
        options=st.session_state["search_keywords"],
        default=st.session_state["search_keywords"],
        label_visibility="collapsed",
        key="active_search",
    )
    removed = [k for k in st.session_state["search_keywords"] if k not in current_search]
    if removed:
        st.session_state["search_keywords"] = current_search
        st.rerun()
    
    # 초기화
    if st.button("🔄 기본 키워드로 초기화", use_container_width=True):
        st.session_state["keyword_pool"] = list(DEFAULT_KEYWORDS)
        st.session_state["search_keywords"] = list(DEFAULT_KEYWORDS[:4])
        st.rerun()
    
    # 4. 검색 실행
    st.divider()
    run_search = st.button("🔍 뉴스 검색", type="primary", use_container_width=True)

# ─── 검색 실행 ───
if run_search:
    if not current_search:
        st.error("검색 키워드를 1개 이상 선택하세요.")
        st.stop()
    with st.spinner("5개 언론사에서 뉴스 수집 중..."):
        collect_result = collect_articles(current_search, WINDOW_MAP[time_window])
        norm_result = normalize_articles(collect_result["raw_articles"])
    st.session_state["search_result"] = {
        "raw": collect_result,
        "normalized": norm_result["normalized_articles"],
    }
    if "briefing_html" in st.session_state:
        del st.session_state["briefing_html"]
    if "analyzed_articles" in st.session_state:
        del st.session_state["analyzed_articles"]
    st.rerun()

# ─── 결과 탭 ───
if "search_result" in st.session_state:
    sr = st.session_state["search_result"]
    articles = sr["normalized"]
    raw_info = sr["raw"]
    
    tab_search, tab_analysis = st.tabs(["📰 검색 결과 & 대시보드", "📊 분석 리포트"])
    
    # ━━━ 탭 1: 검색 결과 + 대시보드 ━━━
    with tab_search:
        # KPI 카드
        st.subheader("📊 수집 현황")
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("총 수집 기사", raw_info["total_count"])
        kpi2.metric("정규화 후", len(articles))
        kpi3.metric("수집 언론사", f"{len(raw_info['source_counts'])}개")
        kpi4.metric("실패 언론사", f"{len(raw_info['failed_sources'])}개")
        
        if articles:
            df = pd.DataFrame(articles)
            
            # ── 대시보드 차트 ──
            st.subheader("📈 대시보드")
            
            chart_row1_col1, chart_row1_col2 = st.columns(2)
            
            with chart_row1_col1:
                # 언론사별 기사 수
                if "source_name" in df.columns:
                    fig = px.bar(
                        df["source_name"].value_counts().reset_index(),
                        x="source_name", y="count",
                        title="언론사별 기사 수",
                        color="source_name",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            with chart_row1_col2:
                # 섹션별 기사 수
                if "section" in df.columns:
                    fig = px.pie(
                        df["section"].value_counts().reset_index(),
                        values="count", names="section",
                        title="섹션별 분포 (IT vs Economy)",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            
            chart_row2_col1, chart_row2_col2 = st.columns(2)
            
            with chart_row2_col1:
                # 날짜별 기사 수
                if "published_at" in df.columns:
                    df_date = df.copy()
                    df_date["date"] = pd.to_datetime(df_date["published_at"], errors="coerce").dt.date
                    date_counts = df_date["date"].value_counts().sort_index().reset_index()
                    date_counts.columns = ["date", "count"]
                    fig = px.line(date_counts, x="date", y="count", title="날짜별 기사 수 추이", markers=True)
                    st.plotly_chart(fig, use_container_width=True)
            
            with chart_row2_col2:
                # 언론사별 소스 분포 (treemap)
                source_section = df.groupby(["source_name", "section"]).size().reset_index(name="count")
                if not source_section.empty:
                    fig = px.treemap(source_section, path=["section", "source_name"], values="count", title="섹션 > 언론사 구조")
                    st.plotly_chart(fig, use_container_width=True)
            
            # ── 기사 목록 ──
            st.subheader("📰 기사 목록")
            for i, a in enumerate(articles[:50], 1):
                st.markdown(f"**{i}.** [{a['title']}]({a['url']}) — {a['source_name']} | {a.get('published_at','')[:10]}")
    
    # ━━━ 탭 2: 분석 리포트 ━━━
    with tab_analysis:
        st.subheader("분석 목적 선택")
        st.caption("검색된 기사를 기반으로 목적에 맞는 리포트를 생성합니다.")
        
        purpose_options = list(PURPOSES.keys())
        selected_purpose = st.radio("목적", purpose_options, horizontal=True, label_visibility="collapsed", index=0)
        purpose_id = PURPOSES[selected_purpose]["id"]
        
        purpose_desc = {
            "lead_generation": "🎯 **신규 고객사 발굴** — 투자/확장/DX 신호를 찾아 접근 후보 리스트와 아웃리치 전략 생성",
            "proposal_support": "📋 **제안서 논리 강화** — 제안 근거를 추출해 제안서 개요, 기대효과, 시장 근거 보고서 작성",
            "competitive_intelligence": "🏢 **경쟁사 분석** — 경쟁사 동향을 분석해 경영진 보고용 리포트 작성",
            "custom_search": "🔍 **종합 분석** — 검색된 기사를 종합 분석해 일반 브리핑 문서 생성",
        }
        st.info(purpose_desc.get(purpose_id, ""))
        
        run_analysis = st.button("📊 리포트 생성", type="primary", use_container_width=True)
        
        if run_analysis:
            progress = st.progress(0, "중복 제거 + 벡터화...")
            
            dedup_result = dedup_and_vectorize(articles)
            filtered = dedup_result["filtered_articles"]
            progress.progress(0.3, f"중복 제거 완료 ({len(filtered)}건)")
            
            progress.progress(0.4, "Bedrock 기사 분석 중...")
            analyzed = analyze_articles(filtered, selected_role, purpose_id)
            progress.progress(0.7, f"분석 완료 ({len(analyzed)}건)")
            
            progress.progress(0.8, "리포트 생성 중...")
            briefing_content = generate_briefing(selected_role, purpose_id, analyzed)
            
            stats = {
                "total_collected": len(articles),
                "after_dedup": len(filtered),
                "analyzed": len(analyzed),
                "high_importance": sum(1 for a in analyzed if a.get("importance", 0) >= 8),
                "avg_purpose_fit": sum(a.get("purpose_fit", 0) for a in analyzed) / max(len(analyzed), 1),
            }
            
            briefing_html = render_briefing_html(selected_role, selected_purpose, briefing_content, analyzed, stats)
            progress.progress(1.0, "✅ 리포트 생성 완료!")
            
            st.session_state["briefing_html"] = briefing_html
            st.session_state["analyzed_articles"] = analyzed
            st.session_state["analysis_stats"] = stats
            st.rerun()
        
        # ── 분석 결과 표시 ──
        if "analyzed_articles" in st.session_state:
            analyzed = st.session_state["analyzed_articles"]
            stats = st.session_state["analysis_stats"]
            
            # KPI
            st.subheader("📊 분석 결과")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("분석 기사", stats["analyzed"])
            c2.metric("중복 제거 후", stats["after_dedup"])
            c3.metric("중요도 8+", stats["high_importance"])
            c4.metric("목적 적합도", f"{stats['avg_purpose_fit']:.0%}")
            c5.metric("수집 원본", stats["total_collected"])
            
            # 분석 차트
            if analyzed:
                df_a = pd.DataFrame(analyzed)
                
                ach1, ach2 = st.columns(2)
                with ach1:
                    if "sentiment" in df_a.columns:
                        fig = px.pie(
                            df_a["sentiment"].value_counts().reset_index(),
                            values="count", names="sentiment",
                            title="감성 분포",
                            color_discrete_map={"positive": "#28a745", "neutral": "#6c757d", "negative": "#dc3545"},
                        )
                        st.plotly_chart(fig, use_container_width=True)
                with ach2:
                    if "opportunity_type" in df_a.columns:
                        fig = px.bar(
                            df_a["opportunity_type"].value_counts().reset_index(),
                            x="opportunity_type", y="count",
                            title="기회유형 분포",
                        )
                        st.plotly_chart(fig, use_container_width=True)
                
                ach3, ach4 = st.columns(2)
                with ach3:
                    if "importance" in df_a.columns:
                        fig = px.histogram(df_a, x="importance", nbins=10, title="중요도 분포")
                        st.plotly_chart(fig, use_container_width=True)
                with ach4:
                    if "source_name" in df_a.columns:
                        fig = px.bar(
                            df_a["source_name"].value_counts().reset_index(),
                            x="source_name", y="count",
                            title="분석 기사 언론사별 분포",
                            color="source_name",
                        )
                        st.plotly_chart(fig, use_container_width=True)
            
            # Top 기사
            st.subheader("🔥 핵심 기사 (중요도 순)")
            top = sorted(analyzed, key=lambda x: x.get("importance", 0), reverse=True)[:10]
            for i, a in enumerate(top, 1):
                with st.expander(f"**{i}. [{a.get('importance','-')}/10]** {a.get('title','')} — {a.get('source_name','')}"):
                    st.write(f"**감성:** {a.get('sentiment','-')} | **기회유형:** {a.get('opportunity_type','-')} | **적합도:** {a.get('purpose_fit',0):.0%}")
                    st.write(f"**요약:** {a.get('summary_ko', a.get('snippet','')[:200])}")
                    st.write(f"**왜 중요한가:** {a.get('why_it_matters','')}")
                    st.write(f"**추천 액션:** {a.get('suggested_action','')}")
                    st.link_button("원문", a.get("url", "#"))
            
            # Briefing Preview
            if "briefing_html" in st.session_state:
                st.subheader("📄 리포트 미리보기")
                st.components.v1.html(st.session_state["briefing_html"], height=600, scrolling=True)
