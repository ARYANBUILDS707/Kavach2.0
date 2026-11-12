"""Stateless inference and shared admission; deliberately no repository or auth service."""

import hashlib
import hmac
import math
import time

from redis import Redis, RedisError

from kavach.api.schemas.public_analyzer import PublicPrediction
from kavach.core.errors import ApiError
from kavach.models.sms_worker import SmsWorkerSupervisor

# Atomic sliding windows, using Redis time across replicas. Only random request IDs, timestamps
# and HMAC IP identifiers are retained, for 60 seconds. Denials do not extend key lifetimes.
RESERVE = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local wait = 0
for i = 1, 2 do
    redis.call('ZREMRANGEBYSCORE', KEYS[i], '-inf', now - 60000)
    if redis.call('ZCARD', KEYS[i]) >= tonumber(ARGV[i]) then
        local first = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
        wait = math.max(wait, tonumber(first[2]) + 60000 - now)
    end
end
if wait > 0 then return wait end
for i = 1, 2 do
    redis.call('ZADD', KEYS[i], now, ARGV[3])
    redis.call('PEXPIRE', KEYS[i], 60000)
end
return 0
"""


class PublicQuota:
    def __init__(
        self, redis: Redis, key: bytes, namespace: str, ip_limit: int, global_limit: int
    ) -> None:
        self._reserve = redis.register_script(RESERVE)
        self._key = key
        self._prefix = f"kavach:{namespace}:ratelimit:public"
        self._limits = [ip_limit, global_limit]

    def reserve(self, client_ip: str, request_id: str) -> None:
        digest = hmac.new(self._key, client_ip.encode(), hashlib.sha256).hexdigest()
        try:
            wait = int(
                self._reserve(
                    keys=[f"{self._prefix}:ip:{digest}", f"{self._prefix}:global"],
                    args=[*self._limits, request_id],
                )
            )
        except RedisError:
            raise ApiError(
                503, "DEPENDENCY_UNAVAILABLE", "Analysis temporarily unavailable"
            ) from None
        if wait:
            raise ApiError(
                429,
                "RATE_LIMITED",
                "Analysis limit reached",
                {"Retry-After": str(max(1, math.ceil(wait / 1000)))},
            )


def analyze(worker: SmsWorkerSupervisor, text: str, deadline: float) -> PublicPrediction:
    started = time.monotonic()
    result = worker.classify(text, deadline)
    if result.reason in ("inference_saturated", "worker_busy"):
        raise ApiError(429, "CAPACITY_EXCEEDED", "Analyzer is busy", {"Retry-After": "2"})
    if result.reason in ("inference_timeout", "deadline_exhausted"):
        raise ApiError(503, "PROCESSING_TIMEOUT", "Analysis timed out", {"Retry-After": "5"})
    if result.outcome != "complete" or result.evidence is None or result.model_ms is None:
        raise ApiError(
            503, "DEPENDENCY_UNAVAILABLE", "Model temporarily unavailable", {"Retry-After": "5"}
        )
    return PublicPrediction(
        prediction=result.evidence.top_label,
        truncated=result.evidence.truncated,
        model_ms=result.model_ms,
        total_ms=max(0, int((time.monotonic() - started) * 1000)),
    )
