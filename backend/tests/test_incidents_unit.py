"""MVP-B3 unit tests without services: the list query contract, the cursor codec and the
503 mapping when PostgreSQL cannot answer. HTTP behaviour is in integration/test_incidents.py."""

import base64
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from kavach.api.schemas.incidents import IncidentEventView, IncidentListQuery
from kavach.db.incident_repository import IncidentFilters, IncidentRow, LinkedEventRow
from kavach.services.incidents import (
    IncidentReadService,
    IncidentsUnavailable,
    InvalidCursor,
    decode_cursor,
    encode_cursor,
)

NOW = datetime(2031, 1, 1, 12, tzinfo=UTC)


def row(occurred_at: datetime = NOW) -> IncidentRow:
    return IncidentRow(uuid4(), "standalone", occurred_at, "unknown", None, "partial", 1, 1, NOW)


def test_the_query_defaults_and_accepts_the_documented_parameters() -> None:
    query = IncidentListQuery.model_validate({})
    assert query.limit == 25 and query.filters() == IncidentFilters()
    query = IncidentListQuery.model_validate(
        {
            "limit": "100",
            "channel": "sms",
            "kind": "standalone",
            "tier": "unknown",
            "from": "2031-01-01T00:00:00+05:30",
            "to": "2031-01-02T00:00:00Z",
        }
    )
    assert query.limit == 100
    assert query.filters().occurred_from == datetime(2030, 12, 31, 18, 30, tzinfo=UTC)


@pytest.mark.parametrize(
    "params",
    [
        {"review_status": "unreviewed"},
        {"occurred_from": "2031-01-01T00:00:00Z"},
        {"limit": "0"},
        {"limit": "101"},
        {"from": "2031-01-01T00:00:00"},
        {"from": "yesterday"},
        {"from": "2031-01-01T00:00:00Z", "to": "2031-01-01T00:00:00Z"},
        {"channel": "email"},
    ],
)
def test_the_query_rejects_everything_else(params: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        IncidentListQuery.model_validate(params)


def test_a_cursor_round_trips_under_the_same_filters_only() -> None:
    filters = IncidentFilters(channel="sms")
    last = row()
    cursor = encode_cursor(filters, last)
    assert decode_cursor(cursor, filters) == (last.occurred_at, last.id)
    for other in (IncidentFilters(), IncidentFilters(channel="call"), IncidentFilters("pair")):
        with pytest.raises(InvalidCursor):
            decode_cursor(cursor, other)


def forge(payload: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "x" * 513,
        "%%%",
        forge([1, 2]),
        forge({"v": 1}),
        forge({"v": 2, "at": NOW.isoformat(), "id": str(uuid4()), "f": "0"}),
        forge({"v": 1, "at": "2031-01-01T00:00:00", "id": str(uuid4()), "f": "0"}),
        forge({"v": 1, "at": NOW.isoformat(), "id": "nope", "f": "0"}),
        forge({"v": 1, "at": 5, "id": str(uuid4()), "f": "0"}),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
    ],
)
def test_malformed_cursors_are_rejected(cursor: str) -> None:
    with pytest.raises(InvalidCursor):
        decode_cursor(cursor, IncidentFilters())


def test_a_forged_cursor_without_the_filter_fingerprint_is_rejected() -> None:
    fingerprinted = json.loads(base64.urlsafe_b64decode(encode_cursor(IncidentFilters(), row())))
    assert set(fingerprinted) == {"v", "at", "id", "f"}
    with pytest.raises(InvalidCursor):
        decode_cursor(forge(fingerprinted | {"f": "0" * 32}), IncidentFilters())


class Unreachable:
    """A session factory whose connection fails like a stopped PostgreSQL."""

    @contextmanager
    def begin(self):  # noqa: ANN202 - mirrors sessionmaker.begin
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))
        yield


def test_an_unreachable_database_is_reported_as_unavailable() -> None:
    service = IncidentReadService(sessions=Unreachable(), clock=lambda: NOW)  # test double
    with pytest.raises(IncidentsUnavailable):
        service.list(IncidentFilters(), 25, None)
    with pytest.raises(IncidentsUnavailable):
        service.detail(uuid4())


def test_event_views_copy_only_allowlisted_evidence() -> None:
    stored = LinkedEventRow(
        id=uuid4(),
        channel="sms",
        occurred_at=NOW,
        received_at=NOW,
        analysis_status="complete",
        processing_ms=12,
        sms_score=None,
        signals={
            "schema_version": 2,
            "stages": {
                "sms_classifier": {
                    "status": "complete",
                    "reason": None,
                    "duration_ms": 7,
                    "model_output": {
                        "labels": {"legitimate": 0.1, "spam": 0.2, "fraud": 0.7},
                        "top_label": "fraud",
                        "score_semantics": "uncalibrated_softmax",
                        "truncated": False,
                        "text": "must never be copied",
                    },
                    "debug": "must never be copied",
                },
                "unexpected_stage": {"status": "complete", "duration_ms": 1},
            },
            "reason_codes": ["sms_model_uncalibrated"],
        },
        model_versions={"sms_classifier": "v", "internal_path": "/models/secret"},
    )
    view = IncidentEventView.of(stored).model_dump_json()
    for leaked in ("must never be copied", "unexpected_stage", "internal_path", "/models"):
        assert leaked not in view
    assert '"fraud":0.7' in view and '"score_semantics":"uncalibrated_softmax"' in view
