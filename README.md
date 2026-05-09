# 📡 MZC Sales Radar

> **메가존클라우드 영업/프리세일즈가 국내 IT/경제 기사에서 고객 기회, 제안 논리, 경쟁사 신호를 빠르게 발견하도록 돕는 AWS Bedrock + AgentCore 기반 Multi-Agent 뉴스 인텔리전스 MVP**

---

## 1. 프로젝트 목적

MZC Sales Radar는 메가존클라우드의 영업 및 프리세일즈 담당자가:
- **고객 기회**를 뉴스에서 선제적으로 포착하고
- **제안 논리**를 외부 근거로 강화하며
- **경쟁사 움직임**을 실시간 모니터링할 수 있도록

5개 국내 주요 언론사(전자신문, ZDNet Korea, 데이터넷, 매일경제, 한국경제)의 기사를 AI가 자동 수집·분석·문서화하는 시스템입니다.

---

## 2. 사용자 페르소나

| 페르소나 | 니즈 | 최종 산출물 |
|---------|------|-----------|
| **영업 담당자** | 고객 접점, 세일즈 기회, 아웃리치 포인트 | Sales Briefing Document (HTML) |
| **프리세일즈 담당자** | 기술 트렌드, 고객 과제, AWS/MZC 솔루션 연결 | Technical Briefing Document (HTML) |

---

## 3. 목적별 사용 시나리오

### A. 신규 고객사 발굴 (Lead Generation)
- 투자 유치, IPO, 글로벌 진출 기업 포착
- CEO DX 의지 표명 기업 식별
- 인프라 확장 신호 감지

### B. 제안서 논리 강화 (Proposal Support)
- 동종 업계 장애/보안 사고 → 클라우드 필요성 근거
- 규제 변화 → 아키텍처 설계 근거
- 기술 도입 사례 → 고객 설득 자료

### C. 경쟁사 분석 (Competitive Intelligence)
- 경쟁사 수주/MOU 동향 파악
- CSP 정책 변화 모니터링
- Win-back 기회 식별

### D. 기타 직접 검색 (Custom Search)
- 사용자 키워드 중심 자유 검색

---

## 4. Agent Workflow

```
Frontend (Streamlit)
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  Orchestrator Agent (전체 워크플로우 제어)              │
│                                                     │
│  1. Keyword Planning Agent (Bedrock 키워드 추천)      │
│  2. Collector Agent (5개 언론사 RSS 수집)             │
│  3. Normalizer Agent (데이터 정규화)                  │
│  4. Dedup & Vector Agent (중복제거 + Bedrock 임베딩)   │
│  5. Insight Analyst Agent (Bedrock 기사 분석)         │
│  6. Persona Briefing Agent (직군별 문서 생성)          │
│  7. Storage Agent (S3/DynamoDB 저장)                 │
└─────────────────────────────────────────────────────┘
    │
    ▼
Dashboard + Briefing Document (HTML)
```

---

## 5. AWS 아키텍처

### MVP (현재 구현)

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Streamlit   │────▶│  Amazon Bedrock  │     │  Google     │
│  (Frontend)  │     │  Claude Sonnet   │     │  News RSS   │
└──────────────┘     │  Titan Embed v2  │     └─────────────┘
       │             └──────────────────┘            │
       │                                             │
       ▼                                             ▼
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Amazon S3   │     │ Amazon DynamoDB  │     │  5개 언론사  │
│  (저장소)     │     │  (메타데이터)     │     │  RSS Feed   │
└──────────────┘     └──────────────────┘     └─────────────┘
```

### 운영 전환 아키텍처

```
EventBridge Scheduler
    ▼
Bedrock AgentCore Runtime ──▶ Orchestrator Agent
    │
    ├── Keyword Planning Agent (Bedrock Claude)
    ├── Collector Agent (RSS via AgentCore Gateway/MCP)
    ├── Normalizer Agent
    ├── Dedup & Vector Agent (Bedrock Embeddings + OpenSearch Serverless)
    ├── Insight Analyst Agent (Bedrock Claude)
    ├── Persona Briefing Agent (Bedrock Claude)
    └── Storage Agent (S3 + DynamoDB)
    
Dashboard: App Runner / QuickSight
Monitoring: CloudWatch + AgentCore Observability
Knowledge: Bedrock Knowledge Bases (MZC offerings, AWS services)
Safety: Bedrock Guardrails
```

---

## 6. MCP / Tool Calling 확장 구조

현재 MVP에서는 각 Agent가 Python 함수를 직접 호출하지만, 운영 전환 시:

1. **AgentCore Gateway**에 RSS 수집, 저장, 리포트 생성을 MCP Tool로 등록
2. Agent가 `@tool` 데코레이터로 정의된 함수를 MCP 프로토콜로 호출
3. `entrypoint.py`의 `analyze_news`, `get_keyword_recommendations`가 이미 tool interface로 분리됨
4. `agentcore add gateway`로 MCP Gateway 추가 후 tool 등록

```python
# 현재 (직접 호출)
from services.rss_client import fetch_all_sources
articles = fetch_all_sources(keywords, window)

# 운영 전환 (MCP Tool 호출)
# AgentCore Gateway가 rss_fetch tool을 MCP 서버로 노출
# Agent가 tool_use로 호출
```

---

## 7. Bedrock Knowledge Bases / RAG 확장 구조

MVP에서는 `config.py`의 정적 데이터를 사용하지만, 운영 전환 시:

| Knowledge Base | 내용 | 용도 |
|---------------|------|------|
| MZC Offerings | 메가존클라우드 서비스 설명 | Briefing에서 MZC 솔루션 추천 |
| AWS Services | AWS 서비스 매핑 | 기술 제안 포인트 연결 |
| Industry Templates | 산업별 제안 템플릿 | 목적별 문서 구성 |
| Sales Playbook | 영업 플레이북 | 추천 액션 생성 |

```bash
# Knowledge Base 추가
agentcore add memory --name MZCOfferings --strategies SEMANTIC
```

---

## 8. 보안 / IAM / Guardrails 설계

### IAM 최소 권한 원칙

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": "arn:aws:bedrock:*::foundation-model/*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject"],
      "Resource": "arn:aws:s3:::mzc-sales-radar-bucket/*"
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:*:*:table/mzc-sales-radar"
    }
  ]
}
```

### Guardrails
- `services/guardrails.py`: 민감 정보 패턴 탐지 + 마스킹
- 운영 전환 시 Bedrock Guardrails API로 PII 필터, 토픽 필터, 과도한 단정 방지

### 보안 원칙
- AWS 자격증명은 코드에 하드코딩하지 않음 (환경변수/IAM Role)
- `.env.example`만 제공, 실제 키는 `.gitignore`로 제외
- 산출물 생성 전 guardrail_check() 실행

---

## 9. 운영 안정성 설계

### Auto Scaling
- AgentCore Runtime: 자동 스케일링 내장
- App Runner: 트래픽 기반 자동 확장

### 모니터링
- CloudWatch Logs: Agent 실행 로그
- CloudWatch Metrics: latency, token usage, failure count
- AgentCore Observability: OpenTelemetry 트레이스

### 장애 복구
- RSS 수집 실패: 해당 언론사만 skip, 나머지 계속 진행
- Bedrock 호출 실패: 기본값 반환 (graceful degradation)
- S3/DynamoDB 실패: 로컬 파일 fallback 자동 전환
- 수집 결과 부족: 키워드 축소 후 재검색 (fallback planning)

---

## 10. 로컬 실행 방법

### 사전 요구사항
- Python 3.11+
- AWS CLI 설정 완료 (`aws configure`)
- Bedrock 모델 접근 권한 (Claude Sonnet, Titan Embed v2)

### 설치 및 실행

```bash
# 1. 프로젝트 이동
cd mzc-sales-radar

# 2. 가상환경 생성
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Mac/Linux

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경변수 설정
copy .env.example .env
# .env 파일에서 AWS_REGION 등 수정

# 5. Streamlit 실행
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 접속

---

## 11. 필요한 AWS 권한

| 서비스 | 권한 | 용도 |
|--------|------|------|
| Amazon Bedrock | `InvokeModel` | LLM 호출 (분석, 키워드 추천, 문서 생성) |
| Amazon Bedrock | `InvokeModel` (Titan Embed) | 기사 벡터화 |
| Amazon S3 | `PutObject`, `GetObject` | 결과 저장 |
| Amazon DynamoDB | `PutItem`, `GetItem` | 메타데이터 저장 |
| Bedrock AgentCore | `*` (배포 시) | Agent Runtime 배포 |

---

## 12. AgentCore Runtime 배포 구조

```bash
# AgentCore CLI 설치
npm install -g @aws/agentcore

# 프로젝트 배포
cd mzc-sales-radar
agentcore deploy

# 배포 상태 확인
agentcore status

# Agent 호출 테스트
agentcore invoke "최근 AWS 관련 뉴스를 분석해줘" --stream

# 로그 확인
agentcore logs
```

### 파일 구조
- `entrypoint.py`: AgentCore Runtime 진입점
- `agentcore.json`: 프로젝트 설정 (agent 이름, model, tools)
- `app.py`: Streamlit Frontend (별도 App Runner 배포)

---

## 13. 데모 시나리오

### 시나리오 1: 영업 - 신규 고객 발굴
1. 직군: **영업** 선택
2. 목적: **신규 고객사 발굴** 선택
3. 키워드: "삼성전자" 입력
4. AI 추천 키워드 클릭 → "투자 유치", "디지털 전환" 등 선택
5. 조회 기간: 3일
6. **분석 실행** 클릭
7. 결과: Top 기사 + Sales Briefing Document 확인

### 시나리오 2: 프리세일즈 - 제안서 근거 수집
1. 직군: **프리세일즈** 선택
2. 목적: **제안서 논리 강화** 선택
3. 키워드: "금융, 보안" 입력
4. AI 추천 → "망분리 완화", "컴플라이언스" 등 선택
5. 분석 실행
6. 결과: Technical Briefing + AWS 솔루션 연결 포인트 확인

### 시나리오 3: 경쟁사 모니터링
1. 직군: **영업** 선택
2. 목적: **경쟁사 분석** 선택
3. 키워드 없이 AI 추천만 사용
4. 분석 실행
5. 결과: 경쟁사 수주 동향 + Win-back 전략 확인

---

## 디렉토리 구조

```
mzc-sales-radar/
├── app.py                    # Streamlit Frontend
├── entrypoint.py             # AgentCore Runtime 진입점
├── config.py                 # 전역 설정
├── agentcore.json            # AgentCore 프로젝트 설정
├── requirements.txt          # Python 의존성
├── .env.example              # 환경변수 예시
├── .gitignore
├── README.md
├── agents/
│   ├── orchestrator.py       # 워크플로우 제어
│   ├── keyword_planner.py    # Bedrock 키워드 추천
│   ├── collector.py          # RSS 수집
│   ├── normalizer.py         # 데이터 정규화
│   ├── dedup_vector.py       # 중복제거 + 벡터화
│   ├── insight_analyst.py    # Bedrock 기사 분석
│   ├── persona_briefing.py   # 직군별 문서 생성
│   └── storage.py            # S3/DynamoDB 저장
├── services/
│   ├── bedrock_client.py     # Bedrock API 호출
│   ├── rss_client.py         # RSS 수집
│   ├── vector_store.py       # 로컬 벡터 저장소
│   ├── s3_store.py           # S3 저장 (+ 로컬 fallback)
│   ├── dynamodb_store.py     # DynamoDB 저장 (+ 로컬 fallback)
│   ├── report_renderer.py    # HTML Briefing 렌더링
│   └── guardrails.py         # 콘텐츠 안전성 검사
└── data/                     # 로컬 fallback 저장소
```

---

## 기술 스택

| 구분 | 기술 | 이유 |
|------|------|------|
| LLM | Amazon Bedrock Claude Sonnet | 한국어 분석 품질, 관리형 서비스 |
| Embedding | Amazon Bedrock Titan Embed v2 | 한국어 지원, 1024차원 |
| Frontend | Streamlit | Python 단일 언어, 빠른 프로토타이핑 |
| 차트 | Plotly | 인터랙티브 차트, Streamlit 호환 |
| 저장소 | S3 + DynamoDB | 서버리스, 확장성, 비용 효율 |
| Agent Runtime | Bedrock AgentCore | 관리형 Agent 실행 환경 |
| 벡터 DB (MVP) | numpy in-memory | 외부 의존성 없이 빠른 구현 |
| 벡터 DB (운영) | OpenSearch Serverless | 대규모 벡터 검색, 관리형 |

---

*Powered by AWS Bedrock + AgentCore | Built for MZC Megathon 2026*
