"""
insight_analyst.py - 인사이트 분석 Agent
──────────────────────────────────────────
설계 이유:
1. Bedrock LLM으로 기사별 중요도/감성/기회유형/적합도를 분석
2. 메가존클라우드 영업/프리세일즈 관점에서 의미를 판단 (단순 요약이 아님)
3. 사용자의 목적에 따라 분석 관점을 조정 (자율적 Agent)
4. 중요도 판단 근거(why_it_matters)를 반드시 생성 (요구사항)
5. 배치 처리로 Bedrock 호출 횟수 최적화 (3~5개씩 묶어서 분석)
"""
import logging

from services.bedrock_client import invoke_model_json

logger = logging.getLogger(__name__)

# 이유: 분석 Agent의 역할을 명확히 정의하는 시스템 프롬프트
# MZC 영업 관점을 주입해 일반적인 뉴스 요약이 아닌 영업 인사이트 생성
_SYSTEM_PROMPT = """당신은 메가존클라우드(MZC)의 시니어 영업/프리세일즈 인텔리전스 분석가입니다.
IT/경제 뉴스 기사를 분석해 MZC 영업팀에게 실질적인 인사이트를 제공합니다.

분석 기준:
- MZC 직접 언급: 매우 높은 중요도
- AWS, 클라우드, 생성형 AI, MSP, 보안, 데이터센터, 디지털 전환: 높은 중요도
- 대기업/공공/금융/제조 IT 투자: 높은 중요도
- 보안 사고, 장애, 규제, 비용 최적화: 높은 중요도
- 경쟁사 수주/파트너십: 중간~높은 중요도
- 단순 광고/행사/채용: 낮은 중요도

반드시 JSON 배열로만 응답하세요."""


def analyze_articles(articles: list[dict], role: str, purpose: str) -> list[dict]:
    """기사 분석 실행.
    
    이유: Orchestrator가 호출하는 tool interface.
    기사를 배치로 묶어 Bedrock에 전달해 분석 효율 극대화.
    
    Args:
        articles: Dedup Agent가 필터링한 기사 리스트
        role: 직군 (영업/프리세일즈)
        purpose: 선택한 목적
    
    Returns:
        분석 결과가 추가된 기사 리스트
    """
    if not articles:
        return []
    
    analyzed = []
    # 이유: 3개씩 배치로 분석 → API 호출 횟수 줄이면서 컨텍스트 유지
    batch_size = 3
    
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        batch_results = _analyze_batch(batch, role, purpose)
        
        # 이유: 분석 결과를 원본 기사에 merge
        for j, article in enumerate(batch):
            if j < len(batch_results):
                article.update(batch_results[j])
            else:
                # 이유: 배치 분석 결과가 부족하면 기본값 적용
                article.update(_default_analysis())
            analyzed.append(article)
    
    logger.info(f"분석 완료: {len(analyzed)}건")
    return analyzed


def _analyze_batch(articles: list[dict], role: str, purpose: str) -> list[dict]:
    """배치 분석 (3개씩).
    이유: 여러 기사를 한 번에 분석해 Bedrock 호출 비용/시간 절약.
    각 기사에 대해 구조화된 분석 결과를 JSON으로 받음.
    """
    articles_text = ""
    for idx, a in enumerate(articles):
        articles_text += f"\n[기사 {idx+1}]\n제목: {a['title']}\n언론사: {a['source_name']}\n요약: {a.get('snippet', '')[:200]}\n"
    
    prompt = f"""직군: {role}
분석 목적: {purpose}

아래 기사들을 메가존클라우드 {role} 관점에서 분석해주세요.

{articles_text}

각 기사에 대해 아래 JSON 배열 형식으로 응답:
[
  {{
    "importance": 1~10 (정수),
    "sentiment": "positive" 또는 "neutral" 또는 "negative",
    "opportunity_type": "sales_opportunity|lead_generation|proposal_evidence|competitive_intelligence|customer_signal|competitor_signal|market_trend|cloud_migration|genai_opportunity|security_risk|data_ai_opportunity|public_sector|partnership|other" 중 하나,
    "relevance_to_mzc": 0.0~1.0,
    "purpose_fit": 0.0~1.0,
    "summary_ko": "한국어 2~3문장 요약",
    "why_it_matters": "MZC 영업/프리세일즈에게 왜 중요한지 1~2문장",
    "suggested_action": "추천 액션 1문장",
    "target_role": "sales" 또는 "presales" 또는 "both"
  }}
]"""

    try:
        result = invoke_model_json(prompt, system=_SYSTEM_PROMPT, max_tokens=4096)
        if isinstance(result, list):
            return result
        logger.warning("분석 결과가 리스트가 아님, 기본값 사용")
    except Exception as e:
        logger.warning(f"배치 분석 실패: {e}")
    
    # 이유: 실패 시 기본값 배열 반환 → 파이프라인 중단 방지
    return [_default_analysis() for _ in articles]


def _default_analysis() -> dict:
    """분석 실패 시 기본값.
    이유: Bedrock 호출 실패해도 파이프라인이 계속 진행되도록 안전한 기본값 제공.
    """
    return {
        "importance": 5,
        "sentiment": "neutral",
        "opportunity_type": "other",
        "relevance_to_mzc": 0.3,
        "purpose_fit": 0.3,
        "summary_ko": "분석 대기 중",
        "why_it_matters": "추가 분석 필요",
        "suggested_action": "기사 원문 확인 권장",
        "target_role": "both",
    }
