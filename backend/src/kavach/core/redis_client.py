"""Redis client lifecycle; Redis only ever holds temporary state, never authoritative records."""

from pydantic import SecretStr
from redis import Redis

SOCKET_TIMEOUT_SECONDS = 2


def create_redis_client(redis_url: SecretStr) -> Redis:
    """Creating the client does not connect; the first command does."""
    return Redis.from_url(
        redis_url.get_secret_value(),
        socket_connect_timeout=SOCKET_TIMEOUT_SECONDS,
        socket_timeout=SOCKET_TIMEOUT_SECONDS,
        health_check_interval=30,
    )


def check_redis(client: Redis) -> None:
    """Raise if Redis does not answer PING."""
    if client.ping() is not True:
        raise ConnectionError("Redis did not acknowledge PING")
