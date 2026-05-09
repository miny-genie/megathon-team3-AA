"""
MZC Sales Radar - AgentCore Runtime Agent
──────────────────────────────────────────
AgentCore에 배포되어 실행되는 메인 Agent.
Streamlit Frontend가 이 Agent를 API로 호출하거나,
agentcore invoke로 직접 호출 가능.

Tools:
1. search_news - 뉴스 수집 + 정규화
2. analyze_news - 분석 + 스코어링
3. recommend_keywords - AI 키워드 추천
4. generate_report - 직군/목적별 briefing 생성
"""
import sys
import os
import json
from datetime import datetime
from collections import Counter

# 프로젝트 루트의 agents/services를 import 가능하게
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model

# MZC Sales Radar 모듈
from agents.collector import collect_articles
from agents.normalizer import normalize_articles
from agents.dedup_vector import dedup_and_vectorize
from agents.insight_analyst import analyze_articles
from agents.persona_briefing import generate_briefing
from agents.keyword_planner import recommend_keywords as _recommend_keywords
from services.scoring import (
    build_user_intent_text, build_article_intent_text,
    calculate_role_keyword_match_score, calculate_recency_score,
    calculate_hotness_score, calculate_final_score, get_source_weight,
)
from services.bedrock_client import get_embedding
from services.trend_analyzer import extract_trend_keywords, calculate_sentiment_overview, calculate_source_reactions
from config import DEFAULT_KEYWORDS, WINDOW_MAP, NOISE_KEYWORDS

app = BedrockAgentCoreApp()
log = app.logger


@tool
def search_news(keywords: str, window: str = "1d") -> str:
    """5개 국내 언론사에서 뉴스를 수집하고 정규화합니다.

    Args:
        keywords: 쉼표로 구분된 검색 키워드
        window: 조회 기간 (1d, 3d, 7d)

    Returns:
        수집 결과 요약 JSON
    """
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] or DEFAULT_KEYWORDS[:3]
    log.info(f"search_news: keywords={kw_list}, window={window}")

    collect_result = collect_articles(kw_list, window)
    norm_result = normalize_articles(collect_result["raw_articles"])
    articles = norm_result["normalized_articles"]

    return json.dumps({
        "total_collected": collect_result["total_count"],
        "normalized": len(articles),
        "source_counts": collect_result["source_counts"],
        "sample_titles": [a["title"] for a in articles[:5]],
    }, ensure_ascii=False)


@tool
def analyze_news(keywords: str, role: str = "영업", window: str = "1d") -> str:
    """뉴스를 수집하고 Bedrock으로 분석 + 스코어링합니다.

    Args:
        keywords: 쉼표로 구분된 검색 키워드
        role: 직군 (영업 또는 프리세일즈)
        window: 조회 기간 (1d, 3d, 7d)

    Returns:
        Top 5 기사 + 스코어 요약 JSON
    """
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] or DEFAULT_KEYWORDS[:3]
    role_key = "sales" if "영업" in role else "presales"
    log.info(f"analyze_news: keywords={kw_list}, role={role_key}, window={window}")

    # 수집 → 정규화 → 중복제거 → 분석
    collect_result = collect_articles(kw_list, window)
    norm_result = normalize_articles(collect_result["raw_articles"])
    dedup_result = dedup_and_vectorize(norm_result["normalized_articles"])
    filtered = dedup_result["filtered_articles"]
    analyzed = analyze_articles(filtered, role, "custom_search")

    # 스코어링
    user_intent = build_user_intent_text(role_key, "custom_search", kw_list, [])
    try:
        user_vector = np.array(get_embedding(user_intent), dtype=np.float32)
    except Exception:
        user_vector = np.zeros(1024, dtype=np.float32)

    opp_counts = Counter(a.get("opportunity_type", "other") for a in analyzed)
    max_cluster = max(opp_counts.values()) if opp_counts else 1

    for art in analyzed:
        art_vector = np.array(art["embedding"], dtype=np.float32) if "embedding" in art else np.zeros_like(user_vector)
        rk = calculate_role_keyword_match_score(user_vector, art_vector)
        rec = calculate_recency_score(art.get("published_at", ""))
        hot = calculate_hotness_score(opp_counts.get(art.get("opportunity_type","other"),1), max_cluster)
        sw = get_source_weight(art.get("source_id",""), role_key, art.get("section",""), "custom_search", art.get("opportunity_type",""))
        noise_p = 0.7 if any(nk in art.get("title","").lower() for nk in NOISE_KEYWORDS) else 1.0
        art["llm_importance"] = art.get("importance", 5)
        art["final_score_100"] = calculate_final_score(art, sw, rk, rec, hot, noise_p)

    analyzed.sort(key=lambda x: x.get("final_score_100", 0), reverse=True)

    top5 = [{
        "title": a["title"],
        "source_name": a.get("source_name",""),
        "final_score_100": a["final_score_100"],
        "summary_ko": a.get("summary_ko",""),
        "suggested_action": a.get("suggested_action",""),
    } for a in analyzed[:5]]

    return json.dumps({"total_analyzed": len(analyzed), "top5": top5}, ensure_ascii=False, indent=2)


@tool
def recommend_keywords(role: str, purpose: str, keywords: str = "") -> str:
    """AI 키워드 추천을 수행합니다.

    Args:
        role: 직군 (영업/프리세일즈)
        purpose: 목적 (lead_generation, proposal_support, competitive_intelligence, custom_search)
        keywords: 현재 키워드 (쉼표 구분)

    Returns:
        추천 키워드 JSON
    """
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] or DEFAULT_KEYWORDS[:3]
    result = _recommend_keywords(kw_list, role, purpose)
    return json.dumps(result, ensure_ascii=False, indent=2)


@tool
def generate_report(role: str, purpose: str, keywords: str, window: str = "1d") -> str:
    """직군/목적별 Briefing 리포트를 생성합니다.

    Args:
        role: 직군
        purpose: 목적
        keywords: 검색 키워드 (쉼표 구분)
        window: 조회 기간

    Returns:
        Briefing 문서 텍스트
    """
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] or DEFAULT_KEYWORDS[:3]
    collect_result = collect_articles(kw_list, window)
    norm_result = normalize_articles(collect_result["raw_articles"])
    dedup_result = dedup_and_vectorize(norm_result["normalized_articles"])
    analyzed = analyze_articles(dedup_result["filtered_articles"], role, purpose)
    briefing = generate_briefing(role, purpose, analyzed)
    return briefing


# ─── Agent 설정 ───
SYSTEM_PROMPT = """당신은 MZC Sales Radar AI 어시스턴트입니다.
메가존클라우드의 영업/프리세일즈 담당자가 뉴스에서 고객 기회를 발견하도록 돕습니다.

사용 가능한 도구:
1. search_news - 5개 언론사에서 뉴스 수집
2. analyze_news - 뉴스 수집 + Bedrock 분석 + 스코어링 (Top 5 반환)
3. recommend_keywords - AI 키워드 추천
4. generate_report - 직군/목적별 Briefing 리포트 생성

사용자의 요청에 따라 적절한 도구를 호출하세요. 한국어로 응답하세요."""

_agent = None

def get_or_create_agent():
    global _agent
    if _agent is None:
        _agent = Agent(
            model=load_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=[search_news, analyze_news, recommend_keywords, generate_report],
        )
    return _agent


@app.entrypoint
async def invoke(payload, context):
    log.info("MZC Sales Radar Agent 호출...")
    agent = get_or_create_agent()
    stream = agent.stream_async(payload.get("prompt"))
    async for event in stream:
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]


if __name__ == "__main__":
    app.run()
