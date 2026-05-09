"""
bedrock_client.py - Amazon Bedrock 호출 서비스
─────────────────────────────────────────────────
설계 이유:
1. Bedrock 호출 로직을 한 곳에 모아 Agent들이 직접 boto3를 다루지 않게 함
2. invoke_model()과 get_embedding() 두 가지 tool interface로 분리
3. JSON parse 실패 시 fallback 처리로 LLM 응답 불안정성 대응
4. retry/timeout을 여기서 관리해 Agent 코드 단순화
"""
import json
import logging
from typing import Optional

import boto3
from botocore.config import Config

from config import AWS_REGION, BEDROCK_MODEL_ID, BEDROCK_EMBEDDING_MODEL_ID

logger = logging.getLogger(__name__)

# 이유: Bedrock 호출 시 timeout과 retry를 명시적으로 설정
# 네트워크 불안정 시에도 graceful하게 실패하도록
_config = Config(
    region_name=AWS_REGION,
    retries={"max_attempts": 3, "mode": "adaptive"},
    read_timeout=60,
)

# 이유: 클라이언트를 모듈 레벨에서 생성해 매 호출마다 재생성하지 않음 (성능)
_bedrock_runtime = None


def _get_client():
    """Bedrock Runtime 클라이언트 lazy initialization.
    이유: import 시점이 아닌 첫 호출 시점에 생성하여 테스트/로컬 실행 유연성 확보
    """
    global _bedrock_runtime
    if _bedrock_runtime is None:
        _bedrock_runtime = boto3.client("bedrock-runtime", config=_config)
    return _bedrock_runtime


def invoke_model(prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    """Bedrock Claude 모델 호출.
    
    이유: 키워드 추천, 기사 분석, briefing 생성 등 모든 LLM 작업의 단일 진입점.
    system prompt와 user prompt를 분리해 Agent별로 역할을 명확히 지정 가능.
    
    Args:
        prompt: 사용자/Agent가 보내는 메시지
        system: 시스템 프롬프트 (Agent 역할 정의)
        max_tokens: 최대 응답 토큰 수
    
    Returns:
        LLM 응답 텍스트
    """
    client = _get_client()
    
    # 이유: Claude Messages API 형식 사용 (Bedrock converse API보다 직접적)
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    try:
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]
    except Exception as e:
        logger.error(f"Bedrock invoke_model 실패: {e}")
        raise


def invoke_model_json(prompt: str, system: str = "", max_tokens: int = 4096) -> Optional[dict]:
    """Bedrock 호출 후 JSON 파싱까지 수행.
    
    이유: Agent들이 구조화된 데이터를 받아야 할 때 사용.
    LLM이 가끔 JSON 외 텍스트를 섞어 반환하므로 파싱 실패 시 None 반환.
    호출자가 fallback 처리를 할 수 있도록 함.
    """
    raw = invoke_model(prompt, system, max_tokens)
    try:
        # 이유: LLM이 ```json ... ``` 형태로 감싸는 경우 대응
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"JSON 파싱 실패, raw 응답 길이: {len(raw)}")
        return None


def get_embedding(text: str) -> list[float]:
    """Bedrock Titan Embedding으로 텍스트 벡터화.
    
    이유: 기사 제목+요약을 벡터로 변환해 유사도 기반 중복 제거에 사용.
    Titan Embed v2는 1024차원 벡터를 반환하며 한국어 지원.
    
    Args:
        text: 벡터화할 텍스트 (최대 8192 토큰)
    
    Returns:
        float 리스트 (1024차원 벡터)
    """
    client = _get_client()
    
    body = {
        "inputText": text[:2000],  # 이유: 임베딩 입력 길이 제한 방어
        "dimensions": 1024,
    }

    try:
        response = client.invoke_model(
            modelId=BEDROCK_EMBEDDING_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        result = json.loads(response["body"].read())
        return result["embedding"]
    except Exception as e:
        logger.error(f"Bedrock embedding 실패: {e}")
        raise
