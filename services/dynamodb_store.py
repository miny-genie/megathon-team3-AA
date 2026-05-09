"""
dynamodb_store.py - DynamoDB 저장 서비스 (로컬 fallback 포함)
──────────────────────────────────────────────────────────────
설계 이유:
1. 기사 메타데이터와 분석 결과를 DynamoDB에 저장 → 빠른 조회/중복 체크
2. PK: article_id (sha256 hash) → URL/title 기반 중복 방지
3. USE_AWS_STORAGE=false이면 로컬 JSON 파일로 fallback
4. put_article()과 get_article()로 CRUD 추상화
"""
import json
import logging
import os
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from config import AWS_REGION, DYNAMODB_TABLE_NAME, USE_AWS_STORAGE

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_LOCAL_DB_PATH = os.path.join(_DATA_DIR, "local_dynamodb.json")


def put_article(article: dict) -> bool:
    """기사 메타데이터 저장.
    
    이유: Normalizer/Insight Agent가 처리한 기사를 영구 저장.
    article_id를 PK로 사용해 동일 기사 재처리 방지.
    
    Args:
        article: article_id를 포함한 기사 딕셔너리
    
    Returns:
        저장 성공 여부
    """
    if USE_AWS_STORAGE:
        return _put_dynamodb(article)
    return _put_local(article)


def get_article(article_id: str) -> Optional[dict]:
    """기사 조회. 이유: 중복 체크 시 기존 저장 여부 확인용."""
    if USE_AWS_STORAGE:
        return _get_dynamodb(article_id)
    return _get_local(article_id)


def article_exists(article_id: str) -> bool:
    """기사 존재 여부 확인. 이유: Dedup Agent에서 빠른 중복 체크."""
    return get_article(article_id) is not None


def _put_dynamodb(article: dict) -> bool:
    """DynamoDB에 저장.
    이유: 운영 환경에서는 DynamoDB의 빠른 key-value 조회로 중복 체크 수행.
    """
    try:
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        table.put_item(Item=article)
        return True
    except ClientError as e:
        logger.warning(f"DynamoDB 저장 실패: {e}")
        return _put_local(article)


def _get_dynamodb(article_id: str) -> Optional[dict]:
    try:
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        table = dynamodb.Table(DYNAMODB_TABLE_NAME)
        resp = table.get_item(Key={"article_id": article_id})
        return resp.get("Item")
    except ClientError:
        return _get_local(article_id)


def _put_local(article: dict) -> bool:
    """로컬 JSON 파일에 저장.
    이유: AWS 없이도 데모 가능. JSON 파일을 간이 DB로 사용.
    """
    os.makedirs(_DATA_DIR, exist_ok=True)
    db = _load_local_db()
    db[article.get("article_id", "")] = article
    _save_local_db(db)
    return True


def _get_local(article_id: str) -> Optional[dict]:
    db = _load_local_db()
    return db.get(article_id)


def _load_local_db() -> dict:
    if os.path.exists(_LOCAL_DB_PATH):
        with open(_LOCAL_DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_local_db(db: dict) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(_LOCAL_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
