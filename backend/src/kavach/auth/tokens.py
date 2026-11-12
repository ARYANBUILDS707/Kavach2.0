"""Opaque session tokens and session-bound CSRF tokens; only SHA-256 digests are stored."""

import base64
import hashlib
import hmac
import secrets

TOKEN_BYTES = 32
# A real token is 43 URL-safe characters; anything far longer is rejected before hashing.
MAX_PRESENTED_TOKEN_LENGTH = 128
CSRF_CONTEXT = b"kavach-csrf-v1"


def new_session_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def csrf_token_for(session_token: str) -> str:
    """Derive the CSRF token from the session token, so it can be re-issued without storing it.

    It is unpredictable without the HttpOnly session cookie, and it changes with every session.
    """
    mac = hmac.new(session_token.encode(), CSRF_CONTEXT, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def presented_token_matches(candidate: str | None, expected_digest: bytes) -> bool:
    if not candidate or len(candidate) > MAX_PRESENTED_TOKEN_LENGTH:
        return False
    return hmac.compare_digest(token_digest(candidate), expected_digest)
