"""
s3_store.py - S3 저장 서비스 (로컬 fallback 포함)
───────────────────────────────────────────────────
설계 이유:
1. USE_AWS_STORAGE=true이면 S3에 저장, false이면 로컬 data/ 폴더에 저장
2. 저장 실패 시 자동으로 로컬 fallback → 데모/발표 시 AWS 없이도 동작
3. S3 path 규칙: s3://{bucket}/mzc-sales-radar/{category}/{date}/
4. Agent는 store() 하나만 호출하면 됨 (저장소 추상화)
"""
import json
import logging
import os
from datetime import datetime

import boto3

from config import AWS_REGION, S3_BUCKET_NAME, USE_AWS_STORAGE

logger = logging.getLogger(__name__)

# 이유: 로컬 fallback 디렉토리
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def store(category: str, data: any, filename: str = None) -> str:
    """데이터 저장 (S3 또는 로컬).
    
    이유: Storage Agent가 호출하는 단일 인터페이스.
    category별로 경로를 분리해 raw/normalized/analysis/briefings 구분.
    
    Args:
        category: raw, normalized, analysis, briefings
        data: 저장할 데이터 (dict/list → JSON, str → 그대로)
        filename: 파일명 (없으면 timestamp 기반 자동 생성)
    
    Returns:
        저장된 경로 (S3 URI 또는 로컬 경로)
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if filename is None:
        ts = datetime.now().strftime("%H%M%S")
        ext = "html" if category == "briefings" else "json"
        filename = f"{category}_{ts}.{ext}"
    
    # 이유: 문자열이면 그대로, dict/list면 JSON 직렬화
    if isinstance(data, (dict, list)):
        content = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        content = str(data)
    
    if USE_AWS_STORAGE:
        return _store_s3(category, today, filename, content)
    else:
        return _store_local(category, today, filename, content)


def _store_s3(category: str, date: str, filename: str, content: str) -> str:
    """S3에 저장.
    이유: 운영 환경에서는 S3에 저장해 영구 보관 + 팀 공유 가능.
    실패 시 로컬 fallback으로 자동 전환.
    """
    key = f"mzc-sales-radar/{category}/{date}/{filename}"
    try:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        s3.put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/html" if filename.endswith(".html") else "application/json",
        )
        path = f"s3://{S3_BUCKET_NAME}/{key}"
        logger.info(f"S3 저장 완료: {path}")
        return path
    except Exception as e:
        logger.warning(f"S3 저장 실패, 로컬 fallback: {e}")
        return _store_local(category, date, filename, content)


def _store_local(category: str, date: str, filename: str, content: str) -> str:
    """로컬 파일 저장.
    이유: AWS 연결 없이도 MVP 데모 가능. data/ 폴더에 카테고리별 저장.
    """
    dir_path = os.path.join(_DATA_DIR, category, date)
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, filename)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    logger.info(f"로컬 저장 완료: {file_path}")
    return file_path
