"""
knowledge_base.py - Bedrock Knowledge Bases (RAG) 연동
───────────────────────────────────────────────────────
Bedrock KB API를 호출해 MZC offerings, AWS 서비스 매핑 등을 검색.
MVP에서는 로컬 fallback, 운영에서는 실제 KB 연동.
"""
import json
import logging
import os

import boto3

from config import AWS_REGION

logger = logging.getLogger(__name__)

# 환경변수로 KB ID 설정 (없으면 로컬 fallback)
KNOWLEDGE_BASE_ID = os.getenv("BEDROCK_KB_ID", "")

_LOCAL_KB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "local_knowledge_context.json")


def retrieve_from_kb(query: str, top_k: int = 3) -> list[dict]:
    """Bedrock Knowledge Base에서 관련 문서 검색 (RAG Retrieve).
    
    KB ID가 설정되어 있으면 실제 API 호출, 없으면 로컬 fallback.
    """
    if KNOWLEDGE_BASE_ID:
        return _retrieve_bedrock_kb(query, top_k)
    return _retrieve_local_kb(query, top_k)


def _retrieve_bedrock_kb(query: str, top_k: int) -> list[dict]:
    """Bedrock Knowledge Bases Retrieve API 호출."""
    try:
        client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
        response = client.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {"numberOfResults": top_k}
            },
        )
        results = []
        for item in response.get("retrievalResults", []):
            results.append({
                "content": item.get("content", {}).get("text", ""),
                "score": item.get("score", 0),
                "source": item.get("location", {}).get("s3Location", {}).get("uri", ""),
            })
        logger.info(f"KB 검색 완료: {len(results)}건")
        return results
    except Exception as e:
        logger.warning(f"Bedrock KB 호출 실패, 로컬 fallback: {e}")
        return _retrieve_local_kb(query, top_k)


def _retrieve_local_kb(query: str, top_k: int) -> list[dict]:
    """로컬 knowledge context에서 키워드 매칭 검색 (MVP fallback)."""
    try:
        with open(_LOCAL_KB_PATH, "r", encoding="utf-8") as f:
            kb = json.load(f)
    except Exception:
        return []

    results = []
    query_lower = query.lower()

    # MZC offerings 검색
    for offering in kb.get("mzc_offerings", []):
        if any(w in offering["desc"].lower() or w in offering["name"].lower() for w in query_lower.split()):
            results.append({"content": f"{offering['name']}: {offering['desc']}", "score": 0.8, "source": "local_kb"})

    # AWS 서비스 매핑 검색
    for category, services in kb.get("aws_services_mapping", {}).items():
        if any(w in category for w in query_lower.split()):
            results.append({"content": f"{category}: {', '.join(services)}", "score": 0.7, "source": "local_kb"})

    # 산업 템플릿 검색
    for industry, template in kb.get("industry_templates", {}).items():
        if industry in query_lower or any(w in template.lower() for w in query_lower.split()):
            results.append({"content": f"[{industry}] {template}", "score": 0.6, "source": "local_kb"})

    return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]
