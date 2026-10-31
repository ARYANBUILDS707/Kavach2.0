"""Redis client lifecycle; Redis only ever holds temporary state, never authoritative records."""

from pydantic import SecretStr
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

# Login fails closed when Redis is slow, so every call is short and never retried: a single
# unreachable or stalled Redis adds at most ~0.5 s (connect) + 0.5 s (reply) to a request.
SOCKET_TIMEOUT_SECONDS = 0.5


def create_redis_client(redis_url: SecretStr) -> Redis:
    """Creating the client does not connect; the first command does."""
    return Redis.from_url(
        redis_url.get_secret_value(),
        socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),
        health_check_interval=30,
    )


def check_redis(client: Redis) -> None:
    """Raise if Redis does not answer PING."""
    if client.ping() is not True:
        raise ConnectionError("Redis did not acknowledge PING")
