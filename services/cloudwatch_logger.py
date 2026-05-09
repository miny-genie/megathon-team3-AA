"""
cloudwatch_logger.py - CloudWatch Logs/Metrics 연동
────────────────────────────────────────────────────
Agent 실행 로그, latency, token usage, failure count를 CloudWatch에 전송.
"""
import logging
import time
import os

import boto3

from config import AWS_REGION

logger = logging.getLogger(__name__)

LOG_GROUP = os.getenv("CLOUDWATCH_LOG_GROUP", "/mzc-sales-radar/agents")
METRIC_NAMESPACE = "MZCSalesRadar"

_cw_logs_client = None
_cw_metrics_client = None


def _get_logs_client():
    global _cw_logs_client
    if _cw_logs_client is None:
        _cw_logs_client = boto3.client("logs", region_name=AWS_REGION)
    return _cw_logs_client


def _get_metrics_client():
    global _cw_metrics_client
    if _cw_metrics_client is None:
        _cw_metrics_client = boto3.client("cloudwatch", region_name=AWS_REGION)
    return _cw_metrics_client


def put_metric(metric_name: str, value: float, unit: str = "Count", dimensions: dict = None):
    """CloudWatch에 커스텀 메트릭 전송."""
    try:
        dims = [{"Name": k, "Value": v} for k, v in (dimensions or {}).items()]
        _get_metrics_client().put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{
                "MetricName": metric_name,
                "Value": value,
                "Unit": unit,
                "Dimensions": dims,
            }],
        )
    except Exception as e:
        logger.debug(f"CloudWatch metric 전송 실패 (무시): {e}")


def log_agent_execution(agent_name: str, duration_ms: float, success: bool, article_count: int = 0):
    """Agent 실행 결과를 CloudWatch Metrics로 전송."""
    put_metric("AgentDuration", duration_ms, "Milliseconds", {"Agent": agent_name})
    put_metric("AgentInvocations", 1, "Count", {"Agent": agent_name})
    if not success:
        put_metric("AgentFailures", 1, "Count", {"Agent": agent_name})
    if article_count > 0:
        put_metric("ArticlesProcessed", article_count, "Count", {"Agent": agent_name})


def log_bedrock_call(model_id: str, latency_ms: float, input_tokens: int = 0, output_tokens: int = 0):
    """Bedrock 호출 메트릭 전송."""
    put_metric("BedrockLatency", latency_ms, "Milliseconds", {"Model": model_id})
    put_metric("BedrockCalls", 1, "Count", {"Model": model_id})
    if input_tokens:
        put_metric("InputTokens", input_tokens, "Count", {"Model": model_id})
    if output_tokens:
        put_metric("OutputTokens", output_tokens, "Count", {"Model": model_id})


class AgentTimer:
    """Agent 실행 시간 측정 컨텍스트 매니저."""
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.start = None

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (time.time() - self.start) * 1000
        success = exc_type is None
        log_agent_execution(self.agent_name, duration, success)
        if not success:
            logger.error(f"[{self.agent_name}] 실패: {exc_val}")
        return False  # 예외 전파
