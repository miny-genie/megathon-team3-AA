"""
entrypoint.py - AgentCore Runtime 배포용 진입점
─────────────────────────────────────────────────
설계 이유:
1. AgentCore Runtime에 배포할 때 사용하는 entrypoint
2. BedrockAgentCoreApp으로 감싸서 agentcore deploy 시 자동 인식
3. Streamlit은 로컬/App Runner용, 이 파일은 AgentCore Runtime용
4. 동일한 agents/services 코드를 재사용 (코드 중복 없음)
5. payload로 직군/목적/키워드를 받아 파이프라인 실행 후 결과 반환

배포 방법:
  agentcore deploy (이 파일이 자동으로 AgentCore Runtime에 올라감)

호출 방법:
  agentcore invoke '{"role":"영업","purpose":"lead_generation","keywords":["AWS","클라우드"]}'
"""
import sys
import os
import json

# 이유: 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agents.orchestrator import run_pipeline
from agents.keyword_planner import recommend_keywords
from config import DEFAULT_KEYWORDS, WINDOW_MAP

app = BedrockAgentCoreApp()
log = app.logger


# ─── Tool 정의 ───
# 이유: AgentCore에서 각 기능을 tool로 노출해 MCP/Gateway 확장 가능

@tool
def analyze_news(role: str, purpose: str, keywords: str, window: str = "1d") -> str:
    """MZC Sales Radar 뉴스 분석 실행.
    
    Args:
        role: 직군 (영업 또는 프리세일즈)
        purpose: 목적 (lead_generation, proposal_support, competitive_intelligence, custom_search)
        keywords: 쉼표로 구분된 키워드
        window: 조회 기간 (1d, 3d, 7d)
    
    Returns:
        분석 결과 요약 JSON
    """
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS[:3]
    
    result = run_pipeline(
        role=role,
        purpose=purpose,
        user_keywords=kw_list,
        recommended_keywords=[],
        time_window=window,
    )
    
    # 이유: AgentCore 응답은 텍스트이므로 핵심 정보만 요약 반환
    stats = result["stats"]
    top_articles = sorted(
        result["analyzed_articles"],
        key=lambda x: x.get("importance", 0),
        reverse=True,
    )[:5]
    
    summary = {
        "stats": stats,
        "top_articles": [
            {"title": a["title"], "importance": a.get("importance"), "summary": a.get("summary_ko", "")}
            for a in top_articles
        ],
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


@tool
def get_keyword_recommendations(role: str, purpose: str, keywords: str) -> str:
    """AI 키워드 추천.
    
    Args:
        role: 직군
        purpose: 목적
        keywords: 사용자 입력 키워드 (쉼표 구분)
    
    Returns:
        추천 키워드 리스트 JSON
    """
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    result = recommend_keywords(kw_list or DEFAULT_KEYWORDS[:3], role, purpose)
    return json.dumps(result, ensure_ascii=False, indent=2)


# ─── Agent 설정 ───
SYSTEM_PROMPT = """당신은 MZC Sales Radar AI 어시스턴트입니다.
메가존클라우드의 영업/프리세일즈 담당자가 뉴스에서 고객 기회를 발견하도록 돕습니다.

사용 가능한 도구:
1. analyze_news - 뉴스 수집 및 분석 실행
2. get_keyword_recommendations - AI 키워드 추천

사용자의 요청에 따라 적절한 도구를 호출하세요."""

_agent = None


def get_or_create_agent():
    global _agent
    if _agent is None:
        from model.load import load_model
        _agent = Agent(
            model=load_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=[analyze_news, get_keyword_recommendations],
        )
    return _agent


@app.entrypoint
async def invoke(payload, context):
    """AgentCore Runtime entrypoint.
    이유: agentcore invoke 또는 API 호출 시 이 함수가 실행됨.
    """
    log.info("MZC Sales Radar Agent 호출...")
    agent = get_or_create_agent()
    stream = agent.stream_async(payload.get("prompt"))
    async for event in stream:
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]


if __name__ == "__main__":
    app.run()
