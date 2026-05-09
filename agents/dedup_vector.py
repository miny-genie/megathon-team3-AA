"""
dedup_vector.py - 중복 제거 및 벡터화 Agent
─────────────────────────────────────────────
설계 이유:
1. URL hash → title hash → embedding similarity 3단계 중복 제거
2. Bedrock Embeddings로 title+snippet 벡터화 → 의미적 유사 기사 제거
3. 노이즈 키워드 기반 광고/채용 기사 필터링
4. MVP에서는 LocalVectorStore, 운영에서는 OpenSearch Serverless로 교체
"""
import logging

from config import NOISE_KEYWORDS
from services.bedrock_client import get_embedding
from services.vector_store import LocalVectorStore

logger = logging.getLogger(__name__)

# 이유: 모듈 레벨 인스턴스로 세션 내 벡터 누적 (Streamlit 세션 동안 유지)
_vector_store = LocalVectorStore()


def dedup_and_vectorize(normalized_articles: list[dict]) -> dict:
    """중복 제거 + 벡터화 실행.
    
    이유: Orchestrator가 호출하는 tool interface.
    3단계 필터링으로 분석 대상을 정제해 Bedrock 호출 비용/시간 절약.
    
    Args:
        normalized_articles: Normalizer Agent가 정제한 기사 리스트
    
    Returns:
        {
            "filtered_articles": [...],
            "duplicate_count": int,
            "noise_count": int,
            "vectorized_count": int,
        }
    """
    _vector_store.clear()  # 이유: 새 분석 세션마다 벡터 저장소 초기화
    
    seen_urls = set()
    seen_titles = set()
    filtered = []
    duplicate_count = 0
    noise_count = 0
    vectorized_count = 0
    
    for article in normalized_articles:
        # ─── 1단계: URL 중복 제거 ───
        # 이유: 동일 URL은 확실한 중복 (가장 빠른 체크)
        url = article["url"]
        if url in seen_urls:
            duplicate_count += 1
            continue
        seen_urls.add(url)
        
        # ─── 2단계: Title 중복 제거 ───
        # 이유: 다른 URL이지만 제목이 동일한 경우 (syndication)
        title_normalized = article["title"].strip().lower()
        if title_normalized in seen_titles:
            duplicate_count += 1
            continue
        seen_titles.add(title_normalized)
        
        # ─── 3단계: 노이즈 필터링 ───
        # 이유: 광고/채용/이벤트 기사는 영업 인사이트와 무관
        if _is_noise(article):
            noise_count += 1
            continue
        
        # ─── 4단계: Embedding 기반 의미적 중복 제거 ───
        # 이유: 속도 우선 모드에서는 skip. URL+title 중복 제거만으로 충분.
        # 환경변수 USE_EMBEDDING_DEDUP=true 설정 시에만 실행.
        import os
        if os.getenv("USE_EMBEDDING_DEDUP", "false").lower() == "true":
            try:
                text_for_embedding = f"{article['title']} {article['snippet']}"
                embedding = get_embedding(text_for_embedding)
                
                if _vector_store.is_duplicate(embedding):
                    duplicate_count += 1
                    continue
                
                _vector_store.add_vector(article["article_id"], embedding)
                article["embedding"] = embedding
                vectorized_count += 1
            except Exception as e:
                logger.warning(f"Embedding 실패, 기사 유지: {e}")
                vectorized_count += 1
        else:
            vectorized_count += 1
        
        filtered.append(article)
    
    # 이유: cluster_size 계산 - opportunity_type 기준으로 같은 유형 기사 수
    opp_counts = {}
    for a in filtered:
        opp = a.get("opportunity_type", "other")
        opp_counts[opp] = opp_counts.get(opp, 0) + 1
    for a in filtered:
        opp = a.get("opportunity_type", "other")
        a["cluster_size"] = opp_counts.get(opp, 1)
        # representative_keyword: 제목에서 가장 긴 명사 후보 추출
        a["representative_keyword"] = _extract_representative_keyword(a)
    
    logger.info(
        f"Dedup 완료: {len(filtered)}건 유효, "
        f"중복 {duplicate_count}건, 노이즈 {noise_count}건 제거"
    )
    
    return {
        "filtered_articles": filtered,
        "duplicate_count": duplicate_count,
        "noise_count": noise_count,
        "vectorized_count": vectorized_count,
    }


def _extract_representative_keyword(article: dict) -> str:
    """제목에서 대표 키워드 추출. 이유: 트렌드 분석과 hotness 계산에 사용."""
    title = article.get("title", "")
    words = [w for w in title.split() if len(w) >= 2]
    # 가장 긴 단어를 대표 키워드로 (간이 구현)
    return max(words, key=len) if words else ""


def _is_noise(article: dict) -> bool:
    """노이즈 기사 판별.
    이유: NOISE_KEYWORDS에 해당하는 단어가 제목에 포함되면 광고/이벤트로 판단.
    """
    title = article.get("title", "").lower()
    return any(kw in title for kw in NOISE_KEYWORDS)
