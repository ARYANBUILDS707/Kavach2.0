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


# --- ingestion keys (M3.2) -----------------------------------------------------------------

# Repeated invalid Bearer credentials per client IP. No specification sets this ceiling; it
# mirrors the only documented one of the same kind, the D08 login IP ceiling.
BEARER_FAILURE_LIMIT = 30
BEARER_FAILURE_WINDOW_SECONDS = 15 * 60
# While an IP is over that ceiling (TD-19, M3.4), its clients' keys are still checked, so other
# clients' failures cannot lock out a valid key. Checks are bounded: a key that authenticated
# within the last day is always checked; any other key only within a small per-IP budget.
BLOCKED_IP_LOOKUPS = 10
BLOCKED_IP_LOOKUP_WINDOW_SECONDS = 60
VALID_KEY_MEMORY_SECONDS = 24 * 60 * 60
# D08 (proposed, adopted for M3.2): 30 event submissions per minute per ingestion key.
SUBMISSIONS_PER_KEY = 30
SUBMISSION_WINDOW_SECONDS = 60
# D08 (adopted for MVP-1, 9 Nov 2026): 120 session-authenticated reads per minute per user.
READS_PER_USER = 120
READ_WINDOW_SECONDS = 60

# KEYS: counter. ARGV: limit, window in ms. Reserve before checking the credential.
RESERVE_ONE_SCRIPT = """
local used = tonumber(redis.call('GET', KEYS[1]) or '0')
if used >= tonumber(ARGV[1]) then
    return {0, math.max(redis.call('PTTL', KEYS[1]), 1000)}
end
if redis.call('INCR', KEYS[1]) == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[2]) end
return {1, 0}
"""
RELEASE_ONE_SCRIPT = """
if tonumber(redis.call('GET', KEYS[1]) or '0') > 0 then redis.call('DECR', KEYS[1]) end
return 1
"""
# KEYS: recently-valid marker for the presented key, blocked-IP lookup counter.
# ARGV: lookup limit, window in ms. A marker admits without spending the budget.
ADMIT_BLOCKED_SCRIPT = """
if redis.call('EXISTS', KEYS[1]) == 1 then return {1, 0} end
local used = tonumber(redis.call('GET', KEYS[2]) or '0')
if used >= tonumber(ARGV[1]) then
    return {0, math.max(redis.call('PTTL', KEYS[2]), 1000)}
end
if redis.call('INCR', KEYS[2]) == 1 then redis.call('PEXPIRE', KEYS[2], ARGV[2]) end
return {1, 0}
"""
# Exact sliding window on Redis server time, so every process uses the same clock.
# KEYS: sorted set of accepted submissions. ARGV: limit, window in ms, unique member.
SLIDING_WINDOW_SCRIPT = """
local now = redis.call('TIME')
local now_ms = tonumber(now[1]) * 1000 + math.floor(tonumber(now[2]) / 1000)
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now_ms - window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[1]) then
    local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    return {0, math.max(tonumber(oldest[2]) + window - now_ms, 1)}
end
redis.call('ZADD', KEYS[1], now_ms, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return {1, 0}
"""


def blocked_for(wait_ms: int) -> Reservation:
    return Reservation(allowed=False, retry_after_seconds=max(1, math.ceil(int(wait_ms) / 1000)))


class BearerAttemptThrottle:
    """Bounds invalid Bearer credentials per client IP, keyed by HMAC; never stores the key.

    The recently-valid marker is an HMAC of the presented key under RATE_LIMIT_HMAC_KEY. It
    never grants access: it only lets the key be checked against PostgreSQL (which enforces
    revocation and expiry) from a blocked IP, and a failed check deletes it.
    """

    def __init__(self, redis: Redis, hmac_key: bytes, namespace: str) -> None:
        self._redis = redis
        self._key = hmac_key
        self._root = f"kavach:{namespace}:ratelimit:bearer"
        self._prefix = f"{self._root}:ip"
        self._reserve = redis.register_script(RESERVE_ONE_SCRIPT)
        self._release = redis.register_script(RELEASE_ONE_SCRIPT)
        self._admit = redis.register_script(ADMIT_BLOCKED_SCRIPT)

    def _redis_key(self, client_ip: str) -> str:
        digest = hmac.new(self._key, f"bearer-ip\0{client_ip}".encode(), hashlib.sha256)
        return f"{self._prefix}:{digest.hexdigest()}"

    def _lookup_key(self, client_ip: str) -> str:
        digest = hmac.new(self._key, f"bearer-lookup\0{client_ip}".encode(), hashlib.sha256)
        return f"{self._root}:lookup:{digest.hexdigest()}"

    def _valid_key(self, presented: str) -> str:
        digest = hmac.new(self._key, f"bearer-valid\0{presented}".encode(), hashlib.sha256)
        return f"{self._root}:valid:{digest.hexdigest()}"

    def admit_blocked(self, client_ip: str, presented: str) -> Reservation:
        """May this key be checked although its IP is over the failure ceiling?"""
        try:
            allowed, wait_ms = self._admit(
                keys=[self._valid_key(presented), self._lookup_key(client_ip)],
                args=[BLOCKED_IP_LOOKUPS, BLOCKED_IP_LOOKUP_WINDOW_SECONDS * 1000],
            )
        except RedisError as error:
            raise ThrottleUnavailable from error
        return Reservation(allowed=True) if allowed == 1 else blocked_for(wait_ms)

    def remember_valid(self, presented: str) -> bool:
        """Best effort after a successful check; a failure only makes the key 'cold'."""
        try:
            self._redis.set(self._valid_key(presented), b"1", ex=VALID_KEY_MEMORY_SECONDS)
        except RedisError:
            return False
        return True

    def forget_valid(self, presented: str) -> bool:
        """Best effort after a failed check (revoked, expired or never valid)."""
        try:
            self._redis.delete(self._valid_key(presented))
        except RedisError:
            return False
        return True

    def reserve(self, client_ip: str) -> Reservation:
        try:
            allowed, wait_ms = self._reserve(
                keys=[self._redis_key(client_ip)],
                args=[BEARER_FAILURE_LIMIT, BEARER_FAILURE_WINDOW_SECONDS * 1000],
            )
        except RedisError as error:
            raise ThrottleUnavailable from error
        return Reservation(allowed=True) if allowed == 1 else blocked_for(wait_ms)

    def release(self, client_ip: str) -> bool:
        """A valid key (or an outage) returns its reservation; best effort."""
        try:
            self._release(keys=[self._redis_key(client_ip)], args=[])
        except RedisError:
            return False
        return True


class SubmissionQuota:
    """D08 per-key submission limit; every authenticated submission counts, replays included."""

    def __init__(self, redis: Redis, hmac_key: bytes, namespace: str) -> None:
        self._key = hmac_key
        self._prefix = f"kavach:{namespace}:ratelimit:ingest:key"
        self._user_prefix = f"kavach:{namespace}:ratelimit:ingest:user"
        self._acquire = redis.register_script(SLIDING_WINDOW_SCRIPT)

    def _redis_key(self, key_id: str) -> str:
        digest = hmac.new(self._key, f"ingest-key\0{key_id}".encode(), hashlib.sha256)
        return f"{self._prefix}:{digest.hexdigest()}"

    def acquire(self, key_id: str, request_id: str) -> Reservation:
        return self._take(self._redis_key(key_id), request_id)

    def acquire_for_user(self, user_id: str, request_id: str) -> Reservation:
        """MVP-B4: an admin's browser submissions, 30 per minute per user, in a namespace of
        their own so they never share a budget with an ingestion key or with reads."""
        digest = hmac.new(self._key, f"ingest-user\0{user_id}".encode(), hashlib.sha256)
        return self._take(f"{self._user_prefix}:{digest.hexdigest()}", request_id)

    def _take(self, redis_key: str, request_id: str) -> Reservation:
        try:
            allowed, wait_ms = self._acquire(
                keys=[redis_key],
                args=[SUBMISSIONS_PER_KEY, SUBMISSION_WINDOW_SECONDS * 1000, request_id],
            )
        except RedisError as error:
            raise ThrottleUnavailable from error
        return Reservation(allowed=True) if allowed == 1 else blocked_for(wait_ms)


class ReadQuota:
    """D08 per-user read limit, one budget shared by every session-authenticated GET and every
    process. Keyed by an HMAC of the user ID; there is no in-process fallback."""

    def __init__(self, redis: Redis, hmac_key: bytes, namespace: str) -> None:
        self._key = hmac_key
        self._prefix = f"kavach:{namespace}:ratelimit:read:user"
        self._acquire = redis.register_script(SLIDING_WINDOW_SCRIPT)

    def _redis_key(self, user_id: str) -> str:
        digest = hmac.new(self._key, f"read-user\0{user_id}".encode(), hashlib.sha256)
        return f"{self._prefix}:{digest.hexdigest()}"

    def acquire(self, user_id: str, request_id: str) -> Reservation:
        try:
            allowed, wait_ms = self._acquire(
                keys=[self._redis_key(user_id)],
                args=[READS_PER_USER, READ_WINDOW_SECONDS * 1000, request_id],
            )
        except RedisError as error:
            raise ThrottleUnavailable from error
        return Reservation(allowed=True) if allowed == 1 else blocked_for(wait_ms)
