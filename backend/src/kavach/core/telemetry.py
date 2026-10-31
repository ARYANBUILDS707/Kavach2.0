"""Sanitized security telemetry: event, reason and request ID only.

Never pass usernames, passwords, tokens, IP addresses or other request content here.
"""

import logging
from uuid import UUID

security_log = logging.getLogger("kavach.security")


def security_event(event: str, reason: str, request_id: UUID | None) -> None:
    security_log.warning(
        "security_event event=%s reason=%s request_id=%s", event, reason, request_id
    )
