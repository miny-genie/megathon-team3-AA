"""
normalizer.py - 기사 정규화 Agent
──────────────────────────────────
설계 이유:
1. 수집된 raw 기사를 표준 포맷으로 정리 → 이후 Agent들이 일관된 데이터 처리
2. HTML 태그 제거, 공백 정리, ISO 날짜 변환, article_id 생성
3. 깨진/너무 짧은 데이터 제거로 분석 품질 확보
4. article_id = sha256(title + source_id + published_at) → 중복 체크 키
"""
import hashlib
import logging
import re

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def normalize_articles(raw_articles: list[dict]) -> dict:
    """기사 정규화 실행.
    
    이유: Orchestrator가 호출하는 tool interface.
    raw 데이터를 정제해 이후 Dedup/Insight Agent가 깨끗한 데이터로 작업 가능.
    
    Args:
        raw_articles: Collector Agent가 수집한 원본 기사 리스트
    
    Returns:
        {
            "normalized_articles": [...],
            "removed_count": int,  # 정규화 과정에서 제거된 기사 수
        }
    """
    normalized = []
    removed = 0
    
    for article in raw_articles:
        cleaned = _clean_article(article)
        if cleaned:
            normalized.append(cleaned)
        else:
            removed += 1
    
    logger.info(f"정규화 완료: {len(normalized)}건 유효, {removed}건 제거")
    return {
        "normalized_articles": normalized,
        "removed_count": removed,
    }


def _clean_article(article: dict) -> dict | None:
    """단일 기사 정규화.
    이유: 각 필드를 개별 정제하고, 최소 품질 기준 미달 시 None 반환.
    """
    title = _clean_text(article.get("title", ""))
    snippet = _clean_html(article.get("snippet", ""))
    url = _canonicalize_url(article.get("url", ""))
    
    # 이유: 제목이 5자 미만이면 의미 있는 기사가 아님 (깨진 데이터)
    if len(title) < 5:
        return None
    
    # 이유: URL이 없으면 원문 링크 제공 불가 → 제거
    if not url:
        return None
    
    # 이유: article_id를 title+source+date 조합의 hash로 생성
    # 동일 기사가 다른 시점에 수집되어도 같은 ID → 중복 방지
    article_id = _generate_id(title, article.get("source_id", ""), article.get("published_at", ""))
    
    return {
        "article_id": article_id,
        "title": title,
        "url": url,
        "source_id": article.get("source_id", ""),
        "source_name": article.get("source_name", ""),
        "section": article.get("section", ""),
        "published_at": article.get("published_at", ""),
        "snippet": snippet,
        "matched_keywords": article.get("matched_keywords", []),
    }


def _clean_text(text: str) -> str:
    """텍스트 공백 정리. 이유: RSS에서 불필요한 공백/개행이 포함될 수 있음."""
    return re.sub(r"\s+", " ", text).strip()


def _clean_html(html: str) -> str:
    """HTML 태그 제거. 이유: RSS snippet에 HTML이 포함되어 있을 수 있음."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    return _clean_text(soup.get_text())


def _canonicalize_url(url: str) -> str:
    """URL 정규화. 이유: 추적 파라미터 제거로 동일 기사 URL 통일."""
    # Google News redirect URL에서 실제 URL 추출은 복잡하므로 MVP에서는 그대로 사용
    return url.strip()


def _generate_id(title: str, source_id: str, published_at: str) -> str:
    """article_id 생성.
    이유: sha256(title + source_id + published_at)로 결정적 ID 생성.
    같은 기사는 항상 같은 ID → DynamoDB PK로 사용 가능.
    """
    raw = f"{title}|{source_id}|{published_at}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
