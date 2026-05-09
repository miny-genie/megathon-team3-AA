"""
orchestrator.py - 전체 워크플로우 제어 Agent
──────────────────────────────────────────────
설계 이유:
1. 모든 Agent의 실행 순서를 관리하는 중앙 컨트롤러
2. Front에서 받은 입력을 각 Agent에 전달하고 결과를 취합
3. 수집 결과가 너무 적으면 키워드 확장 후 재검색 (fallback planning)
4. 각 Agent의 실행 로그를 수집해 Front에서 진행 상황 표시 가능
5. 실패한 Agent가 있어도 가능한 범위까지 진행 (graceful degradation)

워크플로우:
  Keyword Planning → Collector → Normalizer → Dedup & Vector
  → Insight Analyst → Persona Briefing → Storage
"""
import logging
import time

from agents.keyword_planner import recommend_keywords
from agents.collector import collect_articles
from agents.normalizer import normalize_articles
from agents.dedup_vector import dedup_and_vectorize
from agents.insight_analyst import analyze_articles
from agents.persona_briefing import generate_briefing
from agents.storage import store_results
from services.report_renderer import render_briefing_html

logger = logging.getLogger(__name__)

# 이유: 수집 기사가 이 수 미만이면 키워드 확장 후 재검색
_MIN_ARTICLES_THRESHOLD = 3


def run_pipeline(
    role: str,
    purpose: str,
    user_keywords: list[str],
    recommended_keywords: list[str],
    time_window: str,
    progress_callback=None,
) -> dict:
    """전체 파이프라인 실행.
    
    이유: Streamlit Frontend가 호출하는 최상위 진입점.
    progress_callback으로 UI에 실시간 진행 상황 전달.
    
    Args:
        role: 직군 (영업/프리세일즈)
        purpose: 목적 ID (lead_generation, proposal_support, etc.)
        user_keywords: 사용자 입력 키워드
        recommended_keywords: AI 추천 키워드 중 사용자가 선택한 것
        time_window: 조회 기간 (1d, 3d, 7d)
        progress_callback: fn(step_name, message) - UI 진행 표시용
    
    Returns:
        {
            "dashboard_data": {...},
            "briefing_html": str,
            "agent_logs": [...],
            "stats": {...}
        }
    """
    logs = []
    start_time = time.time()
    
    def _log(step, msg):
        entry = {"step": step, "message": msg, "time": time.time() - start_time}
        logs.append(entry)
        logger.info(f"[{step}] {msg}")
        if progress_callback:
            progress_callback(step, msg)
    
    # ─── Step 1: 키워드 조합 ───
    # 이유: user_keywords + recommended_keywords를 합산해 최종 검색 키워드 구성
    _log("키워드 준비", "검색 키워드 조합 중...")
    final_keywords = list(dict.fromkeys(user_keywords + recommended_keywords))
    if not final_keywords:
        final_keywords = user_keywords or ["메가존클라우드", "AWS", "클라우드"]
    
    # ─── Step 2: 뉴스 수집 ───
    _log("뉴스 수집", f"{len(final_keywords)}개 키워드로 5개 언론사 수집 시작")
    collect_result = collect_articles(final_keywords, time_window)
    raw_articles = collect_result["raw_articles"]
    _log("뉴스 수집", f"총 {collect_result['total_count']}건 수집 완료")
    
    # 이유: 수집 결과가 너무 적으면 키워드를 줄여서 재검색 (fallback planning)
    if len(raw_articles) < _MIN_ARTICLES_THRESHOLD and len(final_keywords) > 3:
        _log("재검색", "수집 결과 부족, 핵심 키워드로 재검색")
        collect_result2 = collect_articles(final_keywords[:3], time_window)
        raw_articles.extend(collect_result2["raw_articles"])
    
    # ─── Step 3: 정규화 ───
    _log("정규화", f"{len(raw_articles)}건 정규화 시작")
    norm_result = normalize_articles(raw_articles)
    normalized = norm_result["normalized_articles"]
    _log("정규화", f"{len(normalized)}건 유효 ({norm_result['removed_count']}건 제거)")
    
    # ─── Step 4: 중복 제거 + 벡터화 ───
    _log("중복 제거", f"{len(normalized)}건 중복/노이즈 필터링 시작")
    dedup_result = dedup_and_vectorize(normalized)
    filtered = dedup_result["filtered_articles"]
    _log("중복 제거", f"{len(filtered)}건 유효 (중복 {dedup_result['duplicate_count']}건, 노이즈 {dedup_result['noise_count']}건 제거)")
    
    # ─── Step 5: 인사이트 분석 ───
    _log("인사이트 분석", f"{len(filtered)}건 Bedrock 분석 시작")
    analyzed = analyze_articles(filtered, role, purpose)
    _log("인사이트 분석", f"{len(analyzed)}건 분석 완료")
    
    # ─── Step 6: Briefing 생성 ───
    _log("Briefing 생성", f"{role} / {purpose} 문서 생성 중...")
    briefing_content = generate_briefing(role, purpose, analyzed)
    
    # 이유: 통계 계산 (KPI 카드용)
    stats = {
        "total_collected": collect_result["total_count"],
        "after_dedup": len(filtered),
        "analyzed": len(analyzed),
        "high_importance": sum(1 for a in analyzed if a.get("importance", 0) >= 8),
        "avg_purpose_fit": (
            sum(a.get("purpose_fit", 0) for a in analyzed) / max(len(analyzed), 1)
        ),
    }
    
    # 이유: report_renderer로 HTML 문서 생성
    briefing_html = render_briefing_html(role, purpose, briefing_content, analyzed, stats)
    _log("Briefing 생성", "HTML 문서 생성 완료")
    
    # ─── Step 7: 저장 ───
    _log("저장", "결과 저장 중...")
    storage_result = store_results(
        raw_articles=raw_articles,
        analyzed_articles=analyzed,
        briefing_html=briefing_html,
    )
    _log("저장", f"저장 완료: {storage_result['stored_paths']}")
    
    elapsed = time.time() - start_time
    _log("완료", f"전체 파이프라인 {elapsed:.1f}초 소요")
    
    return {
        "analyzed_articles": analyzed,
        "briefing_html": briefing_html,
        "agent_logs": logs,
        "stats": stats,
        "storage_result": storage_result,
    }
