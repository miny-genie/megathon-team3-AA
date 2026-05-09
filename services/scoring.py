"""
scoring.py - 뉴스 기사 스코어링 서비스
─────────────────────────────────────────
요구사항 기반 최종 점수 산출:
- 언론사 가중치 + 직군/목적 보정
- 사용자 의도 벡터 매칭
- recency, hotness, sentiment, noise
"""
import math
from datetime import datetime, timezone

import numpy as np

# ─── 언론사별 기본 가중치 ───
SOURCE_WEIGHTS = {
    "mk": 1.20,
    "hankyung": 1.20,
    "etnews": 1.15,
    "zdnet": 1.10,
    "datanet": 1.05,
}

# ─── 직군별 의도 프로필 ───
ROLE_INTENT_PROFILES = {
    "sales": """메가존클라우드 영업 담당자.
고객 발굴, 신규 리드, 고객 투자 신호, 디지털 전환 의지, 클라우드 도입 가능성,
아웃리치 포인트, 고객 대화 소재, 경쟁사 수주, 의사결정자 관심사,
제안 가능한 MZC 서비스, 영업 기회와 매출 가능성을 중시한다.""",
    "presales": """메가존클라우드 프리세일즈 담당자.
클라우드 아키텍처, AWS 서비스, 마이그레이션, 보안, 네트워크, 데이터 플랫폼,
생성형 AI, RAG, LLMOps, FinOps, PoC, 기술 검토, 고객 과제,
제안 아키텍처와 기술 솔루션 연결 가능성을 중시한다.""",
}

# ─── 감성 점수 (부정=리스크 높음→가중) ───
SENTIMENT_SCORES = {"positive": 0.6, "neutral": 0.5, "negative": 0.9}


def get_source_weight(source_id: str, role: str = "", section: str = "", purpose: str = "", opportunity_type: str = "") -> float:
    """언론사 가중치 + 직군/목적 보정.
    - role==sales & section==Economy → +0.05
    - role==presales & section==IT → +0.05
    - purpose==competitive_intelligence & competitor_signal → +0.10
    - purpose==proposal_support & proposal_evidence → +0.10
    - purpose==lead_generation & (lead_generation|customer_signal) → +0.10
    """
    base = SOURCE_WEIGHTS.get(source_id, 1.0)
    adj = 0.0
    if role == "sales" and section == "Economy":
        adj += 0.05
    if role == "presales" and section == "IT":
        adj += 0.05
    if purpose == "competitive_intelligence" and opportunity_type == "competitor_signal":
        adj += 0.10
    if purpose == "proposal_support" and opportunity_type == "proposal_evidence":
        adj += 0.10
    if purpose == "lead_generation" and opportunity_type in ("lead_generation", "customer_signal"):
        adj += 0.10
    return round(base + adj, 4)


def build_user_intent_text(role: str, purpose: str, user_keywords: list = None, recommended_keywords: list = None) -> str:
    """사용자 의도 텍스트 생성 (role profile + purpose + keywords)."""
    parts = [ROLE_INTENT_PROFILES.get(role, ""), f"분석 목적: {purpose}"]
    if user_keywords:
        parts.append(f"키워드: {', '.join(user_keywords)}")
    if recommended_keywords:
        parts.append(f"추천 키워드: {', '.join(recommended_keywords)}")
    return " ".join(p for p in parts if p)


def build_article_intent_text(article: dict) -> str:
    """기사 의도 텍스트 (title + snippet + summary + opportunity + why_it_matters)."""
    fields = [article.get("title",""), article.get("snippet",""), article.get("summary_ko",""), article.get("opportunity_type",""), article.get("why_it_matters","")]
    return " ".join(f for f in fields if f)


def calculate_role_keyword_match_score(user_vector: np.ndarray, article_vector: np.ndarray) -> float:
    """코사인 유사도 기반 직군/키워드 매칭 점수 (0~1)."""
    norm_u = np.linalg.norm(user_vector)
    norm_a = np.linalg.norm(article_vector)
    if norm_u == 0 or norm_a == 0:
        return 0.0
    sim = float(np.dot(user_vector, article_vector) / (norm_u * norm_a))
    return max(0.0, min(sim, 1.0))


def calculate_recency_score(published_at) -> float:
    """발행 시간 기반 최신성 점수.
    6h=1.0, 12h=0.85, 24h=0.70, 3d=0.45, 7d=0.25, else=0.10
    """
    now = datetime.now(timezone.utc)
    if isinstance(published_at, str):
        try:
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except Exception:
            return 0.10
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
    """클러스터 크기 기반 화제성 점수. log 정규화."""
    if max_cluster_size <= 1:
        return 0.0
    return min(math.log(1 + cluster_size) / math.log(1 + max_cluster_size), 1.0)


def calculate_final_score(article: dict, source_weight: float, role_keyword_match_score: float, recency_score: float, hotness_score: float, noise_penalty: float = 1.0) -> float:
    """최종 스코어 계산.
    base = importance*0.28 + mzc*0.17 + purpose*0.17 + match*0.18 + sentiment*0.08 + recency*0.07 + hotness*0.05
    final = base * source_weight * noise_penalty * 100 (capped at 100)
    """
    llm = article.get("llm_importance", article.get("importance", 5)) / 10
    mzc = article.get("relevance_to_mzc", 0.5)
    pfit = article.get("purpose_fit", 0.5)
    sent = SENTIMENT_SCORES.get(article.get("sentiment", "neutral"), 0.5)

    base = llm*0.28 + mzc*0.17 + pfit*0.17 + role_keyword_match_score*0.18 + sent*0.08 + recency_score*0.07 + hotness_score*0.05
    final = base * source_weight * noise_penalty
    return round(min(final * 100, 100), 1)


def build_score_reason(article: dict, final_score: float, source_weight: float, role_keyword_match_score: float) -> str:
    """스코어 산출 근거 한국어 설명."""
    source_name = article.get("source_name", "")
    sentiment = article.get("sentiment", "neutral")
    purpose_fit = article.get("purpose_fit", 0)
    mzc = article.get("relevance_to_mzc", 0)

    parts = [f"{source_name} 보도"]
    if source_weight > 1.1:
        parts.append(f"언론사 가중치 {source_weight:.2f}")
    parts.append(f"목적 적합도 {purpose_fit:.2f}")
    parts.append(f"MZC 관련도 {mzc:.2f}")
    parts.append(f"직군/키워드 매칭도 {role_keyword_match_score:.2f}")
    if sentiment == "negative":
        parts.append("부정 리스크가 있어 영업 대응 우선순위가 높습니다")
    return ", ".join(parts) + "."
