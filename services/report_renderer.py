"""
report_renderer.py - HTML Briefing Document 렌더링 서비스
──────────────────────────────────────────────────────────
설계 이유:
1. 최종 산출물은 JSON이 아닌 읽기 좋은 HTML 문서여야 함 (요구사항)
2. 직군/목적별로 문서 구조가 달라지므로 템플릿 기반 렌더링
3. Streamlit에서 바로 표시 가능 + 파일 다운로드 제공
4. 차트/그래프 삽입을 위해 Plotly HTML export 지원
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def render_briefing_html(
    role: str,
    purpose: str,
    briefing_content: str,
    articles: list[dict],
    stats: dict,
) -> str:
    """HTML Briefing Document 생성.
    
    이유: Persona Briefing Agent가 생성한 텍스트를 HTML 문서로 포장.
    CSS 포함 standalone HTML로 만들어 다운로드 시 별도 파일 불필요.
    
    Args:
        role: 직군 (영업/프리세일즈)
        purpose: 선택한 목적
        briefing_content: Bedrock이 생성한 briefing 본문 (마크다운 또는 텍스트)
        articles: 분석된 기사 리스트 (appendix용)
        stats: KPI 통계 (수집 수, 분석 수 등)
    
    Returns:
        완성된 HTML 문자열
    """
    # 이유: 직군별 제목 분기 (요구사항에 명시된 문서 제목)
    if role == "영업":
        title = "MZC Sales Briefing"
    else:
        title = "MZC Presales Technical Briefing"
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # 이유: 기사 목록을 HTML 테이블로 변환 (Appendix)
    article_rows = ""
    for a in articles[:20]:
        importance = a.get("importance", "-")
        sentiment = a.get("sentiment", "-")
        article_rows += f"""
        <tr>
            <td>{a.get('title', '')}</td>
            <td>{a.get('source_name', '')}</td>
            <td>{importance}</td>
            <td>{sentiment}</td>
            <td><a href="{a.get('url', '#')}" target="_blank">원문</a></td>
        </tr>"""
    
    # 이유: standalone HTML (CSS 내장)로 다운로드 시 단일 파일로 완결
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        body {{ font-family: 'Pretendard', -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 40px 20px; color: #1a1a1a; line-height: 1.7; }}
        h1 {{ color: #FF6B00; border-bottom: 3px solid #FF6B00; padding-bottom: 10px; }}
        h2 {{ color: #232F3E; margin-top: 2em; }}
        .meta {{ color: #666; font-size: 0.9em; margin-bottom: 2em; }}
        .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 1.5em 0; }}
        .stat-card {{ background: #f8f9fa; border-radius: 8px; padding: 16px; text-align: center; }}
        .stat-card .number {{ font-size: 2em; font-weight: bold; color: #FF6B00; }}
        .stat-card .label {{ font-size: 0.85em; color: #666; }}
        table {{ width: 100%; border-collapse: collapse; margin: 1em 0; font-size: 0.9em; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
        th {{ background: #232F3E; color: white; }}
        tr:nth-child(even) {{ background: #f8f9fa; }}
        .briefing-content {{ background: #fafbfc; border-left: 4px solid #FF6B00; padding: 20px; margin: 1.5em 0; border-radius: 0 8px 8px 0; }}
        a {{ color: #0073bb; }}
        .footer {{ margin-top: 3em; padding-top: 1em; border-top: 1px solid #ddd; color: #999; font-size: 0.8em; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="meta">
        <strong>직군:</strong> {role} | <strong>목적:</strong> {purpose} | <strong>생성일:</strong> {now}
    </div>
    
    <div class="stats">
        <div class="stat-card"><div class="number">{stats.get('total_collected', 0)}</div><div class="label">수집 기사</div></div>
        <div class="stat-card"><div class="number">{stats.get('after_dedup', 0)}</div><div class="label">중복 제거 후</div></div>
        <div class="stat-card"><div class="number">{stats.get('analyzed', 0)}</div><div class="label">분석 완료</div></div>
        <div class="stat-card"><div class="number">{stats.get('high_importance', 0)}</div><div class="label">중요도 8+</div></div>
    </div>

    <div class="briefing-content">
        {briefing_content}
    </div>

    <h2>📎 Appendix: 주요 기사 목록</h2>
    <table>
        <thead>
            <tr><th>제목</th><th>언론사</th><th>중요도</th><th>감성</th><th>링크</th></tr>
        </thead>
        <tbody>
            {article_rows}
        </tbody>
    </table>

    <div class="footer">
        Powered by MZC Sales Radar | AWS Bedrock + AgentCore | {now}
    </div>
</body>
</html>"""
    
    return html
