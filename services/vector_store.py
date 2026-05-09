"""
vector_store.py - 로컬 벡터 저장소 (MVP용)
─────────────────────────────────────────────
설계 이유:
1. MVP에서는 OpenSearch Serverless 대신 in-memory numpy 벡터 저장소 사용
2. cosine similarity 계산으로 유사 기사 중복 제거 수행
3. 운영 전환 시 이 모듈만 OpenSearch 클라이언트로 교체하면 됨
4. interface를 add_vector() / find_similar()로 통일해 교체 용이
"""
import logging
from typing import Optional

import numpy as np

from config import DEDUP_SIMILARITY_THRESHOLD

logger = logging.getLogger(__name__)


class LocalVectorStore:
    """In-memory 벡터 저장소.
    
    이유: MVP 5시간 내 구현을 위해 외부 의존성 없이 numpy만으로 구현.
    운영 전환 시 OpenSearch Serverless Vector Engine으로 교체.
    동일 interface(add_vector, find_similar)를 유지하면 Agent 코드 변경 불필요.
    """
    
    def __init__(self):
        self._vectors: list[np.ndarray] = []
        self._ids: list[str] = []
    
    def add_vector(self, article_id: str, vector: list[float]) -> None:
        """벡터 추가.
        이유: 기사별 embedding을 저장해 이후 유사도 비교에 사용.
        """
        self._vectors.append(np.array(vector, dtype=np.float32))
        self._ids.append(article_id)
    
    def find_similar(self, vector: list[float], threshold: Optional[float] = None) -> list[str]:
        """주어진 벡터와 유사한 기존 벡터의 article_id 반환.
        
        이유: 새 기사가 기존 기사와 similarity >= threshold이면 중복으로 판단.
        threshold 기본값은 config의 DEDUP_SIMILARITY_THRESHOLD (0.90).
        
        Returns:
            유사한 기사의 article_id 리스트
        """
        if not self._vectors:
            return []
        
        if threshold is None:
            threshold = DEDUP_SIMILARITY_THRESHOLD
        
        query = np.array(vector, dtype=np.float32)
        similar_ids = []
        
        for i, stored in enumerate(self._vectors):
            sim = self._cosine_similarity(query, stored)
            if sim >= threshold:
                similar_ids.append(self._ids[i])
        
        return similar_ids
    
    def is_duplicate(self, vector: list[float]) -> bool:
        """중복 여부 판단 (boolean shortcut).
        이유: Agent에서 간단히 True/False로 중복 체크할 때 사용.
        """
        return len(self.find_similar(vector)) > 0
    
    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """코사인 유사도 계산.
        이유: 벡터 방향 기반 유사도로, 텍스트 의미 유사성 측정에 가장 적합.
        크기(magnitude)에 무관하게 방향만 비교하므로 문장 길이 차이에 강건.
        """
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
    
    @property
    def size(self) -> int:
        return len(self._vectors)
    
    def clear(self) -> None:
        """저장소 초기화. 이유: 새 분석 세션 시작 시 이전 데이터 제거."""
        self._vectors.clear()
        self._ids.clear()
