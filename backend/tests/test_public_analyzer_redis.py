"""Shared quotas against real Redis; no database migration fixture or model double."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from redis import Redis

from kavach.core.errors import ApiError
from kavach.services.public_analyzer import PublicQuota

pytestmark = pytest.mark.integration


def test_shared_atomic_ip_global_limits_and_private_expiring_keys():
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"])
    namespace = f"public-test-{uuid4().hex}"
    quota = PublicQuota(redis, b"test only key", namespace, 3, 5)
    other = PublicQuota(redis, b"test only key", namespace, 3, 5)
    prefix = f"kavach:{namespace}:ratelimit:public:*"

    def attempt(index):
        try:
            (quota if index % 2 else other).reserve("127.0.0.1", str(uuid4()))
            return True
        except ApiError as error:
            assert error.status == 429 and int(error.headers["Retry-After"]) > 0
            return False

    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            assert sum(executor.map(attempt, range(10))) == 3
        other.reserve("127.0.0.2", str(uuid4()))
        other.reserve("127.0.0.3", str(uuid4()))
        with pytest.raises(ApiError) as error:
            quota.reserve("127.0.0.4", str(uuid4()))
        assert error.value.status == 429
        keys = list(redis.scan_iter(prefix))
        assert len(keys) == 4
        for key in keys:
            assert b"127.0.0" not in key
            assert 0 < redis.pttl(key) <= 60000
            assert redis.zcard(key) <= 5
        # Move entries outside the sliding window, proving expiry by timestamp, not local time.
        for key in keys:
            for member in redis.zrange(key, 0, -1):
                redis.zadd(key, {member: 1})
        quota.reserve("127.0.0.1", str(uuid4()))
    finally:
        keys = list(redis.scan_iter(prefix))
        if keys:
            redis.delete(*keys)
        redis.close()
