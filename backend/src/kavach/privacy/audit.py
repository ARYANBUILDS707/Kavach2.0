"""Signed audit records (DATABASE.md audit_records).

The HMAC covers every stored field except the signature, so a modified row is detectable by
anyone holding the key. It does not make the table append-only and cannot reveal deleted rows;
that needs independently controlled storage (see DATABASE.md).
"""

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import insert
from sqlalchemy.orm import Session

from kavach.db.models import AuditRecord

ActorKind = Literal["user", "ingestor", "system"]
SIGNED_FIELDS = (
    "id",
    "actor_user_id",
    "actor_ingest_key_id",
    "actor_kind",
    "action",
    "resource_type",
    "resource_id",
    "request_id",
    "outcome",
    "created_at",
    "key_version",
    "expires_at",
)


def canonical_bytes(fields: Mapping[str, Any]) -> bytes:
    def encode(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat(timespec="microseconds")
        if isinstance(value, UUID):
            return str(value)
        return value

    payload = {name: encode(fields[name]) for name in SIGNED_FIELDS}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class AuditWriter:
    def __init__(
        self, keys: Mapping[str, bytes], active_version: str, retention: timedelta
    ) -> None:
        self._keys = dict(keys)
        self._active = active_version
        self._retention = retention

    def sign(self, fields: Mapping[str, Any]) -> bytes:
        key = self._keys[fields["key_version"]]
        return hmac.new(key, canonical_bytes(fields), hashlib.sha256).digest()

    def verify(self, row: Mapping[str, Any]) -> bool:
        if row["key_version"] not in self._keys:
            return False
        return hmac.compare_digest(self.sign(row), bytes(row["record_hmac"]))

    def record(
        self,
        db: Session,
        *,
        actor_kind: ActorKind,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        request_id: UUID | None,
        now: datetime,
        actor_user_id: UUID | None = None,
        outcome: Literal["success", "denied"] = "success",
    ) -> UUID:
        """Insert within the caller's transaction, so a failed audit write rolls back the change."""
        fields: dict[str, Any] = {
            "id": uuid4(),
            "actor_user_id": actor_user_id,
            "actor_ingest_key_id": None,
            "actor_kind": actor_kind,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            # Operator commands have no HTTP request; they get a fresh correlation ID.
            "request_id": request_id or uuid4(),
            "outcome": outcome,
            "created_at": now,
            "key_version": self._active,
            "expires_at": now + self._retention,
        }
        db.execute(insert(AuditRecord).values(**fields, record_hmac=self.sign(fields)))
        return fields["id"]
