"""
keyword_planner.py - 키워드 기획 및 추천 Agent
─────────────────────────────────────────────────
설계 이유:
1. 사용자의 직군+목적+입력 키워드를 기반으로 Bedrock이 확장 키워드 추천
2. 목적별 seed_keywords를 기반으로 하되, LLM이 맥락에 맞게 추가 추천
3. 단순 Q&A가 아닌 "검색 전략을 세우는" 자율적 Agent (요구사항)
4. tool interface: recommend_keywords() → Agent가 호출하는 도구
"""
import logging

from config import PURPOSES, DEFAULT_KEYWORDS
from services.bedrock_client import invoke_model_json

logger = logging.getLogger(__name__)

# 이유: Bedrock에게 키워드 추천 역할을 부여하는 시스템 프롬프트
# 한국어로 작성 (요구사항), 목적별 맥락을 반영하도록 지시
_SYSTEM_PROMPT = """당신은 메가존클라우드의 영업/프리세일즈 뉴스 검색 전략가입니다.
사용자의 직군, 목적, 입력 키워드를 분석해 Google News RSS 검색에 최적화된 확장 키워드를 추천합니다.

규칙:
- 추천 키워드는 5~10개 사이로 제공
- 한국어 키워드 위주 (영문 고유명사는 그대로)
- 클라우드/AI/보안/데이터/디지털 전환 관련 키워드 우선
- 메가존클라우드 영업 기회와 연결될 수 있는 키워드 선정
- JSON 형식으로만 응답"""


def recommend_keywords(
    user_keywords: list[str],
    role: str,
    purpose: str,
) -> dict:
    """키워드 추천 실행.
    
    이유: Orchestrator가 호출하는 tool interface.
    Bedrock LLM이 직군/목적 맥락을 이해하고 검색 전략을 세움.
    LLM 호출 실패 시 seed_keywords를 fallback으로 반환.
    
    Args:
        user_keywords: 사용자가 입력한 키워드 리스트
        role: 직군 (영업/프리세일즈)
        purpose: 선택한 목적 키
    
    Returns:
        {
            "recommended_keywords": [...],
            "search_strategy": "...",
            "final_keywords": [...]  # user + recommended 합산
        }
    """
    # 이유: 목적에 해당하는 seed 키워드를 가져와 LLM에 컨텍스트로 제공
    purpose_config = None
    for p_name, p_conf in PURPOSES.items():
        if p_conf["id"] == purpose or p_name == purpose:
            purpose_config = p_conf
            break
    
    seed_keywords = purpose_config["seed_keywords"] if purpose_config else []
    
    prompt = f"""직군: {role}
목적: {purpose}
사용자 입력 키워드: {', '.join(user_keywords) if user_keywords else '없음'}
목적별 기본 키워드: {', '.join(seed_keywords)}

위 정보를 바탕으로 Google News RSS 검색에 사용할 확장 키워드를 추천해주세요.

JSON 형식으로 응답:
{{
    "recommended_keywords": ["키워드1", "키워드2", ...],
    "search_strategy": "검색 전략 설명 (1~2문장)"
}}"""

    try:
        result = invoke_model_json(prompt, system=_SYSTEM_PROMPT, max_tokens=1024)
        if result and "recommended_keywords" in result:
            recommended = result["recommended_keywords"]
            strategy = result.get("search_strategy", "")
        else:
            # 이유: LLM 응답 파싱 실패 시 seed_keywords를 fallback으로 사용
            recommended = seed_keywords[:7]
            strategy = "LLM 추천 실패, 기본 키워드 사용"
    except Exception as e:
        logger.warning(f"키워드 추천 실패, fallback 사용: {e}")
        recommended = seed_keywords[:7]
        strategy = f"Bedrock 호출 실패, 기본 키워드 사용: {e}"

    # 이유: 사용자 키워드 + 추천 키워드를 합산해 최종 검색 키워드 구성
    # 중복 제거하면서 순서 유지
    final = list(dict.fromkeys(
        (user_keywords or DEFAULT_KEYWORDS) + recommended
    ))

    return {
        "recommended_keywords": recommended,
        "search_strategy": strategy,
        "final_keywords": final,
    }
