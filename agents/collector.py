"""
collector.py - 뉴스 수집 Agent
────────────────────────────────
설계 이유:
1. 5개 언론사 RSS를 병렬적으로 수집하는 전담 Agent
2. rss_client 서비스를 tool로 호출하는 구조 (tool interface 패턴)
3. 수집 실패한 언론사는 skip하고 로그에 남김 (장애 격리)
4. 수집 결과를 raw_articles로 반환해 다음 Agent에 전달
"""
import logging

from config import NEWS_SOURCES, WINDOW_MAP
from services.rss_client import fetch_all_sources

logger = logging.getLogger(__name__)


def collect_articles(keywords: list[str], window: str) -> dict:
    """뉴스 수집 실행.
    
    이유: Orchestrator가 호출하는 tool interface.
    키워드와 조회 기간을 받아 5개 언론사에서 기사를 수집.
    
    Args:
        keywords: 검색 키워드 리스트 (user + recommended)
        window: 조회 기간 (1d, 3d, 7d)
    
    Returns:
        {
            "raw_articles": [...],
            "total_count": int,
            "source_counts": {"etnews": 5, ...},
            "failed_sources": [...]
        }
    """
    # 이유: UI에서 "1일" 형태로 올 수 있으므로 매핑 처리
    if window in WINDOW_MAP:
        window = WINDOW_MAP[window]
    
    logger.info(f"수집 시작: keywords={keywords[:5]}..., window={window}")
    
    raw_articles = fetch_all_sources(keywords, window)
    
    # 이유: 언론사별 수집 건수를 로그로 남겨 디버깅/모니터링 용이
    source_counts = {}
    for article in raw_articles:
        sid = article["source_id"]
        source_counts[sid] = source_counts.get(sid, 0) + 1
    
    # 이유: 수집 0건인 언론사를 failed로 표시 (Orchestrator가 재시도 판단에 사용)
    failed_sources = [
        sid for sid in NEWS_SOURCES if source_counts.get(sid, 0) == 0
    ]
    
    logger.info(f"수집 완료: 총 {len(raw_articles)}건, 소스별: {source_counts}")
    
    return {
        "raw_articles": raw_articles,
        "total_count": len(raw_articles),
        "source_counts": source_counts,
        "failed_sources": failed_sources,
    }
