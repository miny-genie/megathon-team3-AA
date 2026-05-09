"""뉴스 기사 스코어링 서비스"""

import math
from datetime import datetime, timezone

import numpy as np

# 매체별 가중치
SOURCE_WEIGHTS = {
    "mk": 1.20,
    "hankyung": 1.20,
    "etnews": 1.15,
    "zdnet": 1.10,
    "datanet": 1.05,
}

# 역할별 의도 프로필
ROLE_INTENT_PROFILES = {
    "sales": "클라우드 도입 의사결정자 대상 신규 영업 기회 발굴, 계약 체결, 매출 확대에 관심이 높은 영업 담당자",
    "presales": "기술 검증 및 아키텍처 설계, PoC 지원, 고객 기술 요구사항 분석에 관심이 높은 프리세일즈 엔지니어",
}

# 감성 점수
SENTIMENT_SCORES = {
    "positive": 0.6,
    "neutral": 0.5,
    "negative": 0.9,
}


def get_source_weight(source_id: str, role: str = "", section: str = "", purpose: str = "", opportunity_type: str = "") -> float:
    """매체 및 역할/목적 기반 가중치 반환"""
    base = SOURCE_WEIGHTS.get(source_id, 1.0)
    adjustment = 0.0
    if role == "sales" and opportunity_type in ("new_business", "upsell"):
        adjustment += 0.05
    if role == "presales" and purpose == "technical_validation":
        adjustment += 0.05
    if section == "exclusive":
        adjustment += 0.03
    return round(base + adjustment, 4)


def build_user_intent_text(role: str, purpose: str, user_keywords: list = None, recommended_keywords: list = None) -> str:
    """사용자 의도 텍스트 생성"""
    parts = [ROLE_INTENT_PROFILES.get(role, ""), purpose or ""]
    if user_keywords:
        parts.append(" ".join(user_keywords))
    if recommended_keywords:
        parts.append(" ".join(recommended_keywords))
    return " ".join(p for p in parts if p)


def build_article_intent_text(article: dict) -> str:
    """기사 의도 텍스트 생성"""
    fields = [
        article.get("title", ""),
        article.get("snippet", ""),
        article.get("summary_ko", ""),
        article.get("opportunity_type", ""),
        article.get("why_it_matters", ""),
    ]
    return " ".join(f for f in fields if f)


def calculate_role_keyword_match_score(user_vector: np.ndarray, article_vector: np.ndarray) -> float:
    """코사인 유사도 기반 키워드 매칭 점수 (0~1)"""
    norm_u = np.linalg.norm(user_vector)
    norm_a = np.linalg.norm(article_vector)
    if norm_u == 0 or norm_a == 0:
        return 0.0
    sim = float(np.dot(user_vector, article_vector) / (norm_u * norm_a))
    return max(0.0, min(sim, 1.0))


def calculate_recency_score(published_at: datetime) -> float:
    """발행 시간 기반 최신성 점수"""
    now = datetime.now(timezone.utc)
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    hours = (now - published_at).total_seconds() / 3600
    if hours <= 6:
        return 1.0
    elif hours <= 12:
        return 0.85
    elif hours <= 24:
        return 0.70
    elif hours <= 72:
        return 0.45
    elif hours <= 168:
        return 0.25
    return 0.10


def calculate_hotness_score(cluster_size: int, max_cluster_size: int) -> float:
    """클러스터 크기 기반 화제성 점수"""
    if max_cluster_size <= 0:
        return 0.0
    score = math.log(1 + cluster_size) / math.log(1 + max_cluster_size)
    return min(score, 1.0)


def calculate_final_score(
    article: dict,
    source_weight: float,
    role_keyword_match_score: float,
    recency_score: float,
    hotness_score: float,
    noise_penalty: float = 1.0,
) -> float:
    """최종 스코어 계산"""
    llm_importance = article.get("llm_importance", 5) / 10
    relevance_to_mzc = article.get("relevance_to_mzc", 0.5)
    purpose_fit = article.get("purpose_fit", 0.5)
    sentiment = article.get("sentiment", "neutral")
    sentiment_score = SENTIMENT_SCORES.get(sentiment, 0.5)

    base_score = (
        llm_importance * 0.28
        + relevance_to_mzc * 0.17
        + purpose_fit * 0.17
        + role_keyword_match_score * 0.18
        + sentiment_score * 0.08
        + recency_score * 0.07
        + hotness_score * 0.05
    )
    final = base_score * source_weight * noise_penalty
    return round(min(final * 100, 100), 1)


def build_score_reason(article: dict, final_score: float, source_weight: float, role_keyword_match_score: float) -> str:
    """스코어 산출 근거 설명 생성"""
    title = article.get("title", "제목 없음")
    source = article.get("source_id", "unknown")
    sentiment = article.get("sentiment", "neutral")
    reasons = []
    if final_score >= 80:
        reasons.append(f"'{title}' 기사는 {final_score}점으로 매우 높은 관련도를 보입니다.")
    else:
        reasons.append(f"'{title}' 기사는 {final_score}점을 기록했습니다.")
    if source_weight > 1.1:
        reasons.append(f"매체({source}) 신뢰도 가중치가 {source_weight}로 높습니다.")
    if role_keyword_match_score > 0.7:
        reasons.append(f"사용자 관심 키워드와의 매칭도가 {role_keyword_match_score:.2f}로 우수합니다.")
    if sentiment == "negative":
        reasons.append("부정적 뉴스로 리스크 대응 관점에서 중요도가 높습니다.")
    return " ".join(reasons)
