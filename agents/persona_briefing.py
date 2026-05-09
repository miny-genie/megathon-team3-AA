"""
persona_briefing.py - 페르소나별 Briefing 문서 생성 Agent
──────────────────────────────────────────────────────────
설계 이유:
1. 분석 결과를 직군별/목적별 최종 문서로 변환 (JSON → 읽기 좋은 문서)
2. 영업: 고객 대화 포인트, 아웃리치 메시지, MZC Offering 중심
3. 프리세일즈: 기술 트렌드, AWS 솔루션 연결, Discovery Questions 중심
4. 목적별로 문서 강조점이 달라짐 (Lead/Proposal/Competitive)
5. Bedrock LLM이 문서 본문을 생성 → report_renderer가 HTML로 포장
"""
import logging

from services.bedrock_client import invoke_model
from services.guardrails import guardrail_check

logger = logging.getLogger(__name__)


def generate_briefing(
    role: str,
    purpose: str,
    analyzed_articles: list[dict],
) -> str:
    """Briefing 문서 본문 생성.
    
    이유: Orchestrator가 호출하는 tool interface.
    Bedrock LLM이 분석된 기사를 기반으로 직군/목적에 맞는 문서를 작성.
    Guardrail 검사를 통과한 후 반환.
    
    Args:
        role: 직군 (영업/프리세일즈)
        purpose: 선택한 목적
        analyzed_articles: Insight Agent가 분석한 기사 리스트
    
    Returns:
        HTML 형식의 briefing 본문 텍스트
    """
    # 이유: 직군별로 문서 섹션 구조가 다름 (요구사항에 명시)
    if role == "영업":
        sections = _sales_sections(purpose)
    else:
        sections = _presales_sections(purpose)
    
    # 이유: 상위 기사만 briefing에 포함 (중요도 순 정렬)
    top_articles = sorted(
        analyzed_articles, key=lambda x: x.get("importance", 0), reverse=True
    )[:10]
    
    articles_context = _format_articles_for_prompt(top_articles)
    
    prompt = f"""당신은 메가존클라우드의 {role} 전문 브리핑 작성자입니다.

직군: {role}
분석 목적: {purpose}

아래 분석된 기사들을 바탕으로 브리핑 문서를 작성해주세요.

{articles_context}

문서 구조 (각 섹션을 <h2> 태그로 구분):
{sections}

작성 규칙:
- HTML 태그 사용 (<h2>, <p>, <ul>, <li>, <strong>)
- 한국어로 작성
- 구체적이고 실행 가능한 내용 위주
- 각 섹션 2~5문장
- 기사 출처를 인용할 때 언론사명 포함
"""

    try:
        content = invoke_model(prompt, max_tokens=4096)
    except Exception as e:
        logger.error(f"Briefing 생성 실패: {e}")
        content = f"<h2>Briefing 생성 실패</h2><p>Bedrock 호출 오류: {e}</p>"
    
    # 이유: 생성된 문서에 민감 정보/과도한 단정이 없는지 검사
    check_result = guardrail_check(content)
    if not check_result["safe"]:
        logger.warning(f"Guardrail 경고: {check_result['warnings']}")
    
    return check_result["cleaned_text"]


def _sales_sections(purpose: str) -> str:
    """영업 문서 섹션 구조.
    이유: 요구사항에 명시된 영업 briefing 8개 섹션.
    목적별로 강조점 힌트를 추가해 LLM이 맥락에 맞게 작성하도록 유도.
    """
    purpose_hint = {
        "lead_generation": "신규 접근 후보, 고객 신호, 아웃리치 타이밍, 예상 니즈 중심으로 작성",
        "proposal_support": "제안 논리, 시장 근거, 동종 업계 사례, 기술 도입 명분 중심으로 작성",
        "competitive_intelligence": "경쟁사 움직임, 방어 논리, 차별화 포인트, Win-back 가능성 중심으로 작성",
        "custom_search": "입력 키워드 중심의 일반 briefing",
    }.get(purpose, "")
    
    return f"""1. Executive Summary
2. 목적별 핵심 인사이트 ({purpose_hint})
3. Today's Top Sales Signals
4. 고객 대화 포인트
5. 아웃리치 메시지 초안
6. 제안 가능한 MZC Offering
7. 우선 접근해야 할 산업/고객군
8. 참고 기사 요약"""


def _presales_sections(purpose: str) -> str:
    """프리세일즈 문서 섹션 구조.
    이유: 요구사항에 명시된 프리세일즈 briefing 8개 섹션.
    기술 관점의 분석과 AWS 솔루션 매핑을 강조.
    """
    purpose_hint = {
        "lead_generation": "기술 니즈 예측, 아키텍처 제안 포인트 중심",
        "proposal_support": "기술 도입 근거, 레퍼런스 아키텍처, PoC 시나리오 중심",
        "competitive_intelligence": "기술 차별화, 마이그레이션 전략, 벤치마크 중심",
        "custom_search": "입력 키워드 관련 기술 트렌드 중심",
    }.get(purpose, "")
    
    return f"""1. Executive Summary
2. 목적별 핵심 인사이트 ({purpose_hint})
3. Today's Top Technical Signals
4. 기술 트렌드 요약
5. AWS/MZC 솔루션 연결 포인트
6. 고객 미팅 Discovery Questions
7. 제안/PoC 아이디어
8. 참고 기사 요약"""


def _format_articles_for_prompt(articles: list[dict]) -> str:
    """분석된 기사를 LLM 프롬프트용 텍스트로 변환.
    이유: 구조화된 형태로 제공해 LLM이 정확히 참조할 수 있도록.
    """
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"""[기사 {i}]
제목: {a.get('title', '')}
언론사: {a.get('source_name', '')}
중요도: {a.get('importance', '-')}/10
감성: {a.get('sentiment', '-')}
기회유형: {a.get('opportunity_type', '-')}
요약: {a.get('summary_ko', a.get('snippet', '')[:150])}
왜 중요한가: {a.get('why_it_matters', '')}
추천 액션: {a.get('suggested_action', '')}
""")
    return "\n".join(lines)
