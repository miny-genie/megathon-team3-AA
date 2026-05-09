"""
guardrails.py - 콘텐츠 안전성 검사 (규칙 기반 + Bedrock Guardrails API)
──────────────────────────────────────────────────────────────────────────
1단계: 규칙 기반 필터링 (민감정보 패턴, 과도한 단정)
2단계: Bedrock Guardrails API 호출 (GUARDRAIL_ID 설정 시)
"""
import json
import logging
import os
import re

import boto3

from config import AWS_REGION

logger = logging.getLogger(__name__)

# Bedrock Guardrails 설정 (환경변수로 관리)
GUARDRAIL_ID = os.getenv("BEDROCK_GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.getenv("BEDROCK_GUARDRAIL_VERSION", "DRAFT")

# 규칙 기반 민감정보 패턴
_SENSITIVE_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{5}\b",       # 주민등록번호
    r"\b\d{3}-\d{3,4}-\d{4}\b",     # 전화번호
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",  # 이메일
]

_OVERSTATEMENT_KEYWORDS = [
    "반드시 성공", "100% 보장", "절대 실패하지 않",
    "확실히 수주", "무조건",
]


def guardrail_check(text: str) -> dict:
    """콘텐츠 안전성 검사 (규칙 기반 + Bedrock Guardrails API).
    
    Returns:
        {"safe": bool, "warnings": list, "cleaned_text": str}
    """
    warnings = []
    cleaned = text

    # ─── 1단계: 규칙 기반 필터링 ───
    for pattern in _SENSITIVE_PATTERNS:
        matches = re.findall(pattern, cleaned)
        if matches:
            warnings.append(f"민감 정보 패턴 감지: {len(matches)}건 마스킹됨")
            cleaned = re.sub(pattern, "[REDACTED]", cleaned)

    for keyword in _OVERSTATEMENT_KEYWORDS:
        if keyword in cleaned:
            warnings.append(f"과도한 단정 표현 감지: '{keyword}'")

    # ─── 2단계: Bedrock Guardrails API ───
    if GUARDRAIL_ID:
        bedrock_result = _apply_bedrock_guardrail(cleaned)
        if bedrock_result:
            if bedrock_result.get("action") == "BLOCKED":
                warnings.append(f"Bedrock Guardrail 차단: {bedrock_result.get('reason', '')}")
                cleaned = "[콘텐츠가 가드레일에 의해 차단되었습니다]"
            elif bedrock_result.get("action") == "MODIFIED":
                cleaned = bedrock_result.get("output", cleaned)
                warnings.append("Bedrock Guardrail에 의해 내용이 수정되었습니다")

    is_safe = len(warnings) == 0
    if not is_safe:
        logger.warning(f"Guardrail 경고: {warnings}")

    return {"safe": is_safe, "warnings": warnings, "cleaned_text": cleaned}


def _apply_bedrock_guardrail(text: str) -> dict | None:
    """Bedrock Guardrails ApplyGuardrail API 호출.
    PII 필터, 토픽 필터, 과도한 단정 방지 등 기업용 안전성 검사.
    """
    try:
        client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        response = client.apply_guardrail(
            guardrailIdentifier=GUARDRAIL_ID,
            guardrailVersion=GUARDRAIL_VERSION,
            source="OUTPUT",
            content=[{"text": {"text": text}}],
        )
        action = response.get("action", "NONE")
        if action == "GUARDRAIL_INTERVENED":
            # 차단된 경우
            outputs = response.get("outputs", [])
            output_text = outputs[0].get("text", "") if outputs else ""
            assessments = response.get("assessments", [])
            reason = ""
            if assessments:
                for a in assessments:
                    for policy in a.get("topicPolicy", {}).get("topics", []):
                        reason += policy.get("name", "") + " "
                    for policy in a.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
                        reason += policy.get("type", "") + " "
            return {"action": "BLOCKED" if not output_text else "MODIFIED", "output": output_text, "reason": reason.strip()}
        return {"action": "PASSED"}
    except Exception as e:
        logger.debug(f"Bedrock Guardrail 호출 실패 (규칙 기반만 적용): {e}")
        return None
