"""
guardrails.py - 콘텐츠 안전성 검사 서비스
──────────────────────────────────────────────
설계 이유:
1. 기업용 산출물에 민감 정보가 포함될 가능성 대응 (요구사항)
2. MVP에서는 규칙 기반 필터링, 운영 전환 시 Bedrock Guardrails API 연동
3. 부적절한 표현, 과도한 단정, 민감 정보 패턴을 사전 차단
4. guardrail_check() 하나로 Agent가 간단히 호출 가능
"""
import logging
import re

logger = logging.getLogger(__name__)

# 이유: 기업 산출물에 포함되면 안 되는 패턴들
# 실제 운영에서는 Bedrock Guardrails의 PII 필터, 토픽 필터로 대체
_SENSITIVE_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{5}\b",       # 주민등록번호 패턴
    r"\b\d{3}-\d{3,4}-\d{4}\b",     # 전화번호 패턴
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # 이메일
]

# 이유: 영업 문서에서 과도한 단정 표현은 법적 리스크 유발 가능
_OVERSTATEMENT_KEYWORDS = [
    "반드시 성공", "100% 보장", "절대 실패하지 않",
    "확실히 수주", "무조건",
]


def guardrail_check(text: str) -> dict:
    """콘텐츠 안전성 검사.
    
    이유: Persona Briefing Agent가 생성한 문서를 최종 출력 전에 검사.
    문제 발견 시 경고와 함께 마스킹된 텍스트 반환.
    
    Args:
        text: 검사할 텍스트
    
    Returns:
        {"safe": bool, "warnings": list, "cleaned_text": str}
    """
    warnings = []
    cleaned = text
    
    # 이유: 민감 정보 패턴 탐지 및 마스킹
    for pattern in _SENSITIVE_PATTERNS:
        matches = re.findall(pattern, cleaned)
        if matches:
            warnings.append(f"민감 정보 패턴 감지: {len(matches)}건 마스킹됨")
            cleaned = re.sub(pattern, "[REDACTED]", cleaned)
    
    # 이유: 과도한 단정 표현 경고 (마스킹은 하지 않고 경고만)
    for keyword in _OVERSTATEMENT_KEYWORDS:
        if keyword in cleaned:
            warnings.append(f"과도한 단정 표현 감지: '{keyword}'")
    
    is_safe = len(warnings) == 0
    if not is_safe:
        logger.warning(f"Guardrail 경고: {warnings}")
    
    return {
        "safe": is_safe,
        "warnings": warnings,
        "cleaned_text": cleaned,
    }
