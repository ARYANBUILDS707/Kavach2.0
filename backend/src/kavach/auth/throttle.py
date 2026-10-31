"""Shared, Redis-backed login throttling (C-06). There is no in-process fallback.

Each attempt is reserved atomically *before* the password is checked, so concurrent requests on
any number of processes cannot exceed the limits. A successful login refunds its reservation.
Keys are HMACs of the canonical username and client IP, never the values themselves.
"""

import hashlib
import hmac
import math
from dataclasses import dataclass

from redis import Redis, RedisError

ACCOUNT_IP_LIMIT = 5  # D08: failed logins per account and IP per window
IP_LIMIT = 30  # D08: failed logins per IP per window
WINDOW_SECONDS = 15 * 60

# KEYS: account+IP counter, IP counter. ARGV: account limit, IP limit, window in ms.
# Returns {1, 0} when the attempt is reserved, or {0, retry_after_ms} when it is blocked.
RESERVE_SCRIPT = """
local account = tonumber(redis.call('GET', KEYS[1]) or '0')
local ip = tonumber(redis.call('GET', KEYS[2]) or '0')
local wait = 0
if account >= tonumber(ARGV[1]) then wait = math.max(wait, redis.call('PTTL', KEYS[1])) end
if ip >= tonumber(ARGV[2]) then wait = math.max(wait, redis.call('PTTL', KEYS[2])) end
if account >= tonumber(ARGV[1]) or ip >= tonumber(ARGV[2]) then
    return {0, math.max(wait, 1000)}
end
if redis.call('INCR', KEYS[1]) == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[3]) end
if redis.call('INCR', KEYS[2]) == 1 then redis.call('PEXPIRE', KEYS[2], ARGV[3]) end
return {1, 0}
"""

# Successful login: forget the account+IP failures and return this attempt's IP reservation.
RELEASE_SCRIPT = """
redis.call('DEL', KEYS[1])
if tonumber(redis.call('GET', KEYS[2]) or '0') > 0 then redis.call('DECR', KEYS[2]) end
return 1
"""


class ThrottleUnavailable(Exception):
    """Redis could not confirm the throttle state; login must fail closed."""


@dataclass(frozen=True)
class Reservation:
    allowed: bool
    retry_after_seconds: int = 0


class LoginThrottle:
    def __init__(self, redis: Redis, hmac_key: bytes, namespace: str) -> None:
        self._redis = redis
        self._key = hmac_key
        self._prefix = f"kavach:{namespace}:ratelimit:login"
        self._reserve = redis.register_script(RESERVE_SCRIPT)
        self._release = redis.register_script(RELEASE_SCRIPT)

    def _keys(self, username: str, client_ip: str) -> list[str]:
        account = hmac.new(self._key, f"acct\0{username}\0{client_ip}".encode(), hashlib.sha256)
        ip = hmac.new(self._key, f"ip\0{client_ip}".encode(), hashlib.sha256)
        return [f"{self._prefix}:acct:{account.hexdigest()}", f"{self._prefix}:ip:{ip.hexdigest()}"]

    def reserve(self, username: str, client_ip: str) -> Reservation:
        try:
            allowed, wait_ms = self._reserve(
                keys=self._keys(username, client_ip),
                args=[ACCOUNT_IP_LIMIT, IP_LIMIT, WINDOW_SECONDS * 1000],
            )
        except RedisError as error:
            raise ThrottleUnavailable from error
        if allowed == 1:
            return Reservation(allowed=True)
        return Reservation(allowed=False, retry_after_seconds=math.ceil(int(wait_ms) / 1000))

    def release(self, username: str, client_ip: str) -> bool:
        """Best effort; a failed refund only leaves the counters more conservative."""
        try:
            self._release(keys=self._keys(username, client_ip), args=[])
        except RedisError:
            return False
        return True
