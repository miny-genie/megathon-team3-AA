#!/bin/bash
# ═══════════════════════════════════════════════════════════
# MZC Sales Radar - AgentCore Deploy Script (AWS CloudShell)
# ═══════════════════════════════════════════════════════════
# 사용법: AWS 콘솔 → CloudShell 열고 이 스크립트 전체를 붙여넣기
# ═══════════════════════════════════════════════════════════

set -e

echo "=== 1. S3에서 프로젝트 다운로드 ==="
rm -rf ~/MZCSalesRadarAgent
aws s3 sync s3://mzc-sales-radar-bucket/agentcore-project/ ~/MZCSalesRadarAgent/
cd ~/MZCSalesRadarAgent

echo "=== 2. Node.js + AgentCore CLI 설치 ==="
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash - 2>/dev/null || true
sudo yum install -y nodejs 2>/dev/null || true
npm install -g @aws/agentcore

echo "=== 3. uv 설치 ==="
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 2>/dev/null || export PATH="$HOME/.local/bin:$PATH"

echo "=== 4. Git 초기화 ==="
cd ~/MZCSalesRadarAgent
git init
git add -A
git commit -m "agentcore deploy from cloudshell"

echo "=== 5. AgentCore Deploy ==="
agentcore deploy --yes

echo "=== 6. 상태 확인 ==="
agentcore status

echo "=== 완료! ==="
echo "테스트: agentcore invoke '최근 AWS 관련 뉴스를 분석해줘' --stream"
