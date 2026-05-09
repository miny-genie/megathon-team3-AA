# deploy.ps1 - MZC Sales Radar 배포 스크립트
# 사용법: .\deploy.ps1 "커밋 메시지"
# 동작: 코드 → S3 sync + git commit & push (동시 배포)

param(
    [string]$Message = "update: code sync"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MZC Sales Radar - Deploy" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. S3 Sync
Write-Host "`n[1/3] S3 sync..." -ForegroundColor Yellow
aws s3 sync $ProjectDir s3://mzc-sales-radar-bucket/code/ `
    --exclude ".venv/*" `
    --exclude ".git/*" `
    --exclude "__pycache__/*" `
    --exclude "data/*" `
    --exclude "*.pyc" `
    --region us-east-1 `
    --delete
Write-Host "  S3 sync 완료!" -ForegroundColor Green

# 2. Git commit
Write-Host "`n[2/3] Git commit..." -ForegroundColor Yellow
Set-Location $ProjectDir
git add -A
git commit -m $Message 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Commit: $Message" -ForegroundColor Green
} else {
    Write-Host "  변경사항 없음 (skip)" -ForegroundColor Gray
}

# 3. Git push
Write-Host "`n[3/3] Git push..." -ForegroundColor Yellow
git push origin main 2>&1
Write-Host "  Push 완료!" -ForegroundColor Green

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  배포 완료! (S3 + GitHub)" -ForegroundColor Cyan
Write-Host "  S3: s3://mzc-sales-radar-bucket/code/" -ForegroundColor Gray
Write-Host "  Git: https://github.com/miny-genie/megathon-team3-AA" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
