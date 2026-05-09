"""
config.py - MZC Sales Radar 전역 설정
─────────────────────────────────────────
설계 이유:
1. 모든 상수/설정을 한 곳에 모아 변경 시 코드 수정 최소화
2. 환경변수 → .env → 기본값 순으로 fallback하여 로컬/운영 동일 코드 사용
3. RSS 템플릿, 언론사 메타, 기본 키워드를 config로 분리해 비개발자도 수정 가능
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── AWS 설정 ───
# 이유: 환경변수로 분리해 코드에 credential 하드코딩 방지 (보안 원칙)
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
BEDROCK_EMBEDDING_MODEL_ID = os.getenv("BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "mzc-sales-radar-bucket")
DYNAMODB_TABLE_NAME = os.getenv("DYNAMODB_TABLE_NAME", "mzc-sales-radar")
# true이면 S3/DynamoDB 사용, false이면 로컬 파일 fallback
USE_AWS_STORAGE = os.getenv("USE_AWS_STORAGE", "false").lower() == "true"

# ─── 언론사 메타데이터 ───
# 이유: 5개 언론사만 대상으로 하며, site 제한 RSS로 정확도 확보
# Google News 일반 검색은 노이즈가 많아 site: 필터 필수
NEWS_SOURCES = {
    "etnews": {"name": "전자신문", "section": "IT", "domain": "etnews.com"},
    "zdnet": {"name": "ZDNet Korea", "section": "IT", "domain": "zdnet.co.kr"},
    "datanet": {"name": "데이터넷", "section": "IT", "domain": "datanet.co.kr"},
    "mk": {"name": "매일경제", "section": "Economy", "domain": "mk.co.kr"},
    "hankyung": {"name": "한국경제", "section": "Economy", "domain": "hankyung.com"},
}

# ─── RSS URL 템플릿 ───
# 이유: Google News RSS의 site: 연산자로 특정 언론사만 필터링
# {DOMAIN}, {KEYWORDS}, {WINDOW}를 런타임에 치환
RSS_TEMPLATE = (
    "https://news.google.com/rss/search?"
    "q={KEYWORDS}%20site%3A{DOMAIN}%20when%3A{WINDOW}"
    "&hl=ko&gl=KR&ceid=KR%3Ako"
)

# ─── 조회 기간 매핑 ───
# 이유: UI 선택값 → Google News when: 파라미터 변환
WINDOW_MAP = {"1일": "1d", "3일": "3d", "7일": "7d"}

# ─── 기본 키워드 ───
# 이유: 사용자가 아무것도 입력하지 않아도 MZC 관련 기사를 수집할 수 있도록
# 추후 비개발자가 이 리스트만 수정하면 기본 검색 범위 변경 가능
DEFAULT_KEYWORDS = [
    "메가존클라우드", "AWS", "클라우드", "생성형 AI",
    "MSP", "보안", "데이터센터", "디지털 전환",
]

# ─── 직군 설정 ───
# 이유: MVP에서는 영업/프리세일즈만 실제 동작, 나머지는 DEMO 표시용
ROLES = {
    "영업": {"supported": True, "target_role": "sales"},
    "프리세일즈": {"supported": True, "target_role": "presales"},
    "마케팅": {"supported": False},
    "컨설턴트": {"supported": False},
    "경영진": {"supported": False},
}

# ─── 목적 설정 ───
# 이유: 목적별로 키워드 추천 전략과 briefing 구성이 달라짐
PURPOSES = {
    "신규 고객사 발굴 (Lead Generation)": {
        "id": "lead_generation",
        "seed_keywords": [
            "투자 유치", "시리즈", "IPO", "상장 예비심사",
            "글로벌 진출", "해외 진출", "현지 법인",
            "신년사", "DX", "디지털 전환", "AI 도입",
        ],
    },
    "제안서 논리 강화 (Proposal Support)": {
        "id": "proposal_support",
        "seed_keywords": [
            "트래픽 폭주", "서비스 장애", "보안 사고",
            "망분리 완화", "가이드라인", "컴플라이언스",
            "FinOps", "GenAI 클라우드 비용", "클라우드 네이티브",
        ],
    },
    "경쟁사 분석 (Competitive Intelligence)": {
        "id": "competitive_intelligence",
        "seed_keywords": [
            "베스핀글로벌", "클루커스", "LG CNS", "수주", "MOU",
            "AWS", "Azure", "GCP", "신규 리전", "가격 인상", "프로모션",
        ],
    },
    "기타 직접 검색 (Custom Search)": {
        "id": "custom_search",
        "seed_keywords": [],
    },
}

# ─── 노이즈 필터 키워드 ───
# 이유: 광고/채용/이벤트 기사는 영업 인사이트와 무관하므로 제거
NOISE_KEYWORDS = [
    "특가", "할인", "쿠폰", "이벤트", "프로모션",
    "쇼핑", "채용", "모집", "증정",
]

# ─── 중복 제거 임계값 ───
# 이유: cosine similarity 0.90 이상이면 사실상 동일 기사로 판단
DEDUP_SIMILARITY_THRESHOLD = 0.90

# ─── 분석 설정 ───
TOP_K_ARTICLES = 10  # 대시보드에 표시할 상위 기사 수
# 이유: 조회 기간 내 모든 기사를 가져옴. Google News RSS는 보통 최대 100건 반환.
# 제한을 두지 않고 RSS가 반환하는 전체를 수집.
MAX_ARTICLES_PER_SOURCE = None
