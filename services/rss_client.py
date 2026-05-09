"""
rss_client.py - 5개 언론사 Google News RSS 수집 서비스
──────────────────────────────────────────────────────────
설계 이유:
1. Google News RSS의 site: 연산자로 특정 언론사만 필터링 → 노이즈 최소화
2. 키워드를 OR 조합으로 구성해 검색 범위 확보
3. 언론사별 독립 수집 → 한 곳 실패해도 나머지는 정상 수집 (장애 격리)
4. feedparser로 RSS XML 파싱 → 표준 라이브러리 수준의 안정성
"""
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import feedparser
import requests

from config import NEWS_SOURCES, RSS_TEMPLATE

logger = logging.getLogger(__name__)

# 이유: Google News가 봇 차단할 수 있으므로 브라우저 UA 사용
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def create_rss_url(source_id: str, keywords: list[str], window: str) -> str:
    """RSS URL 생성 함수.
    
    이유: 요구사항에 명시된 create_rss_url(source_id, keywords, window) 인터페이스.
    키워드를 OR로 연결해 하나라도 매칭되면 수집되도록 함.
    URL encode를 정확히 처리해 한글 키워드도 안전하게 전달.
    
    Args:
        source_id: etnews, zdnet, datanet, mk, hankyung
        keywords: 검색 키워드 리스트
        window: 1d, 3d, 7d
    
    Returns:
        완성된 Google News RSS URL
    """
    source = NEWS_SOURCES[source_id]
    # 이유: OR 연산자로 키워드 조합 → 하나라도 포함된 기사 수집
    keyword_query = " OR ".join(keywords)
    encoded_keywords = quote(keyword_query)
    
    url = RSS_TEMPLATE.format(
        KEYWORDS=encoded_keywords,
        DOMAIN=source["domain"],
        WINDOW=window,
    )
    return url


def fetch_rss(source_id: str, keywords: list[str], window: str) -> list[dict]:
    """단일 언론사 RSS 수집.
    
    이유: Agent가 호출하는 tool interface.
    수집 실패 시 빈 리스트 반환 + 로그 기록으로 전체 파이프라인 중단 방지.
    
    Returns:
        수집된 기사 리스트 (title, url, source_id, published_at, snippet 포함)
    """
    url = create_rss_url(source_id, keywords, window)
    source_meta = NEWS_SOURCES[source_id]
    
    try:
        # 이유: timeout 10초로 느린 응답 시 빠르게 skip
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"RSS fetch 실패 [{source_id}]: {e}")
        return []

    feed = feedparser.parse(resp.content)
    articles = []
    
    for entry in feed.entries:
        # 이유: published_parsed가 없을 수 있으므로 안전하게 처리
        pub_date = _parse_date(entry.get("published_parsed"))
        
        articles.append({
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "source_id": source_id,
            "source_name": source_meta["name"],
            "section": source_meta["section"],
            "published_at": pub_date,
            "snippet": entry.get("summary", ""),
            "matched_keywords": keywords,
        })
    
    logger.info(f"[{source_id}] {len(articles)}건 수집 완료")
    return articles


def fetch_all_sources(keywords: list[str], window: str) -> list[dict]:
    """5개 언론사 전체 수집.
    
    이유: Collector Agent가 한 번에 모든 언론사를 수집할 때 사용.
    각 언론사 독립 실행으로 부분 실패 허용.
    """
    all_articles = []
    for source_id in NEWS_SOURCES:
        articles = fetch_rss(source_id, keywords, window)
        all_articles.extend(articles)
    return all_articles


def _parse_date(parsed_time) -> Optional[str]:
    """feedparser의 time_struct를 ISO 문자열로 변환.
    이유: 표준 ISO 포맷으로 통일해 정렬/필터링 용이하게 함.
    """
    if parsed_time:
        try:
            dt = datetime(*parsed_time[:6])
            return dt.isoformat()
        except Exception:
            pass
    return datetime.now().isoformat()
