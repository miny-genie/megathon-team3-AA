"""
storage.py - 저장 Agent
─────────────────────────
설계 이유:
1. 파이프라인의 각 단계 결과를 영구 저장하는 전담 Agent
2. S3 (raw/normalized/analysis/briefings) + DynamoDB (metadata) 이중 저장
3. AWS 실패 시 로컬 fallback 자동 전환 (서비스 레이어에서 처리)
4. 저장 결과를 로그로 반환해 Orchestrator가 상태 추적 가능
"""
import logging

from services.s3_store import store as s3_store
from services.dynamodb_store import put_article

logger = logging.getLogger(__name__)


def store_results(
    raw_articles: list[dict] = None,
    normalized_articles: list[dict] = None,
    analyzed_articles: list[dict] = None,
    briefing_html: str = None,
) -> dict:
    """분석 결과 저장 실행.
    
    이유: Orchestrator가 파이프라인 마지막에 호출하는 tool interface.
    각 카테고리별로 S3에 저장하고, 분석된 기사는 DynamoDB에도 저장.
    
    Args:
        raw_articles: 원본 수집 기사
        normalized_articles: 정규화된 기사
        analyzed_articles: 분석 완료 기사
        briefing_html: 생성된 HTML briefing
    
    Returns:
        {"stored_paths": {...}, "dynamodb_count": int}
    """
    stored_paths = {}
    dynamodb_count = 0
    
    # 이유: 각 단계별 결과를 별도 경로에 저장 → 디버깅/감사 추적 용이
    if raw_articles:
        path = s3_store("raw", raw_articles)
        stored_paths["raw"] = path
    
    if normalized_articles:
        path = s3_store("normalized", normalized_articles)
        stored_paths["normalized"] = path
    
    if analyzed_articles:
        path = s3_store("analysis", analyzed_articles)
        stored_paths["analysis"] = path
        
        # 이유: 분석된 기사를 DynamoDB에 개별 저장 → 빠른 조회/중복 체크
        for article in analyzed_articles:
            # embedding은 DynamoDB에 저장하지 않음 (크기 제한)
            article_for_db = {k: v for k, v in article.items() if k != "embedding"}
            if put_article(article_for_db):
                dynamodb_count += 1
    
    if briefing_html:
        path = s3_store("briefings", briefing_html, filename="briefing.html")
        stored_paths["briefing"] = path
    
    logger.info(f"저장 완료: paths={stored_paths}, DynamoDB={dynamodb_count}건")
    
    return {
        "stored_paths": stored_paths,
        "dynamodb_count": dynamodb_count,
    }
