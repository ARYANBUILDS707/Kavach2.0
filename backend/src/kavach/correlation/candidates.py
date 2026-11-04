"""Temporary candidate index in Redis (DATABASE.md "Redis keys", ARCHITECTURE.md, D05).

One sorted set per pseudonymous subscriber:
    kavach:{env}:candidate:{identity_key_version}:{subscriber_digest hex}
member `{kind}:{event UUID}`, score = event time in epoch milliseconds. Nothing else is
stored: no text, audio, raw subscriber token, payload or credential. Writes are idempotent
(re-adding a member changes nothing), so replays and duplicates add no evidence.

D05 (proposed, adopted for M3.2): a pair may only form when |event-time difference| <= 30
minutes, and an arriving event may only start a pair when it is at most 10 minutes late.
So an arriving event's time is never older than arrival - 10 min and its partner never older
than that - 30 min: candidates older than 40 minutes can never match. Members are pruned
below that horizon on every write and the key's TTL is 40 minutes, refreshed on write.

This index only *accelerates* lookup. It never creates incidents or conclusions, a match is
not trusted correlation, and PostgreSQL remains authoritative (`rebuild` restores it).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis import Redis, RedisError

CORRELATION_WINDOW = timedelta(minutes=30)
ALLOWED_LATENESS = timedelta(minutes=10)
CANDIDATE_HORIZON = CORRELATION_WINDOW + ALLOWED_LATENESS
# Bounds memory per subscriber: the D08 per-key submission rate over the 40-minute horizon.
MAX_CANDIDATES_PER_SUBSCRIBER = 30 * 40

# KEYS: candidate set. ARGV: score, member, prune-below score, TTL ms, cap.
# Returns how many members the cap evicted (0 normally).
INDEX_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', '(' .. ARGV[3])
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[2])
local evicted = 0
local size = redis.call('ZCARD', KEYS[1])
if size > tonumber(ARGV[5]) then
    evicted = redis.call('ZREMRANGEBYRANK', KEYS[1], 0, size - tonumber(ARGV[5]) - 1)
end
redis.call('PEXPIRE', KEYS[1], ARGV[4])
return evicted
"""


class CandidateIndexUnavailable(Exception):
    """Redis could not be updated or read; PostgreSQL still holds every event."""


@dataclass(frozen=True)
class Candidate:
    event_id: UUID
    kind: str
    event_time: datetime


def epoch_ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def is_late(event_time: datetime, received_at: datetime) -> bool:
    """D05: an event more than 10 minutes late may not start a new pair."""
    return received_at - event_time > ALLOWED_LATENESS


def is_indexable(event_time: datetime, received_at: datetime) -> bool:
    """Older events can never be matched by anything arriving now or later."""
    return event_time >= received_at - CANDIDATE_HORIZON


class CandidateIndex:
    def __init__(self, redis: Redis, namespace: str) -> None:
        self._redis = redis
        self._prefix = f"kavach:{namespace}:candidate"
        self._index = redis.register_script(INDEX_SCRIPT)

    def key(self, identity_key_version: str, subscriber_digest: bytes) -> str:
        return f"{self._prefix}:{identity_key_version}:{subscriber_digest.hex()}"

    def add(
        self,
        *,
        identity_key_version: str,
        subscriber_digest: bytes,
        event_id: UUID,
        kind: str,
        event_time: datetime,
        received_at: datetime,
    ) -> int:
        """Index one event; returns evictions caused by the cap. Too-old events are skipped."""
        if not is_indexable(event_time, received_at):
            return 0
        try:
            return int(
                self._index(
                    keys=[self.key(identity_key_version, subscriber_digest)],
                    args=[
                        epoch_ms(event_time),
                        f"{kind}:{event_id}",
                        epoch_ms(received_at - CANDIDATE_HORIZON),
                        int(CANDIDATE_HORIZON.total_seconds() * 1000),
                        MAX_CANDIDATES_PER_SUBSCRIBER,
                    ],
                )
            )
        except RedisError as error:
            raise CandidateIndexUnavailable from error

    def near(
        self, identity_key_version: str, subscriber_digest: bytes, event_time: datetime
    ) -> list[Candidate]:
        """Candidates within the D05 window of `event_time`. Not a trusted match by itself."""
        try:
            rows = self._redis.zrangebyscore(
                self.key(identity_key_version, subscriber_digest),
                epoch_ms(event_time - CORRELATION_WINDOW),
                epoch_ms(event_time + CORRELATION_WINDOW),
                withscores=True,
            )
        except RedisError as error:
            raise CandidateIndexUnavailable from error
        candidates = []
        for member, score in rows:
            text = member.decode() if isinstance(member, bytes) else member
            kind, _, event_id = text.partition(":")
            candidates.append(
                Candidate(
                    event_id=UUID(event_id),
                    kind=kind,
                    event_time=datetime.fromtimestamp(score / 1000, UTC),
                )
            )
        return candidates
