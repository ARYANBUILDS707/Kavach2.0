"""MVP-B6 contract tests (draft): the generated OpenAPI document is pinned in Git and checked
against API.md "SMS MVP-1 contract", so the frontend can type against a reviewed file.

Regenerate the snapshot after an approved contract change, then review the diff:

    KAVACH_WRITE_OPENAPI_SNAPSHOT=1 uv run --project backend --locked \
        python -m pytest backend/tests/test_contract.py -k snapshot
"""

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from kavach.api.schemas.events import AdminReceiptResponse
from kavach.api.schemas.incidents import IncidentDetailResponse, IncidentListResponse
from kavach.core.config import Settings
from kavach.main import create_app

BACKEND = Path(__file__).resolve().parents[1]
SNAPSHOT = BACKEND / "contract" / "openapi.json"
API_MD = BACKEND.parent / "docs" / "API.md"
MVP_SECTION = "## SMS MVP-1 contract"
# Fields the detail and list responses must never carry anywhere (API.md, owner decision).
FORBIDDEN_FIELDS = {
    "source",
    "external_event_id",
    "text",
    "sender_id",
    "subscriber_token",
    "subscriber_digest",
    "payload_digest",
    "identity_key_version",
    "payload_key_version",
    "evidence",
    "note",
}


def generated() -> dict[str, Any]:
    return create_app(Settings(app_env="test", log_level="INFO")).openapi()


def rendered(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def test_the_committed_openapi_snapshot_matches_the_application() -> None:
    current = rendered(generated())
    if os.environ.get("KAVACH_WRITE_OPENAPI_SNAPSHOT") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(current)
    assert SNAPSHOT.exists(), "run with KAVACH_WRITE_OPENAPI_SNAPSHOT=1 to create it"
    assert SNAPSHOT.read_text() == current, (
        "The API changed: update docs/API.md if approved, regenerate the snapshot "
        "(see this module's docstring) and review the diff"
    )


def test_the_mvp_routes_and_methods_are_exactly_the_documented_ones() -> None:
    paths = generated()["paths"]
    mvp = {
        "/api/v1/auth/login": {"post"},
        "/api/v1/auth/session": {"get"},
        "/api/v1/auth/logout": {"post"},
        "/api/v1/system/models": {"get"},
        "/api/v1/incidents": {"get"},
        "/api/v1/incidents/{incident_id}": {"get"},
    }
    for path, methods in mvp.items():
        assert set(paths[path]) == methods, path
    # Postponed beyond MVP-1: no review, stream or bulk route exists.
    for path in paths:
        assert "review" not in path and "stream" not in path, path


def test_the_incident_list_parameters_match_the_contract() -> None:
    operation = generated()["paths"]["/api/v1/incidents"]["get"]
    parameters = {p["name"]: p for p in operation["parameters"]}
    assert set(parameters) == {"limit", "cursor", "kind", "tier", "channel", "from", "to"}
    assert all(p["in"] == "query" and p["required"] is False for p in parameters.values())
    assert parameters["limit"]["schema"] == {
        "default": 25,
        "maximum": 100,
        "minimum": 1,
        "type": "integer",
    }
    assert parameters["channel"]["schema"]["enum"] == ["sms", "call"]
    assert parameters["kind"]["schema"]["enum"] == ["standalone", "pair"]
    assert parameters["tier"]["schema"]["enum"] == ["unknown", "low", "medium", "high", "critical"]
    assert "review_status" not in parameters


def property_names(schema: dict[str, Any], definitions: dict[str, Any]) -> set[str]:
    """Every property name reachable from a schema, following `$ref`s."""
    seen: set[str] = set()
    pending = [schema]
    visited: set[str] = set()
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                name = ref.rsplit("/", 1)[-1]
                if name not in visited:
                    visited.add(name)
                    pending.append(definitions[name])
            seen |= set(node.get("properties", {}))
            pending += list(node.values())
        elif isinstance(node, list):
            pending += node
    return seen


@pytest.mark.parametrize("path", ["/api/v1/incidents", "/api/v1/incidents/{incident_id}"])
def test_incident_responses_carry_no_forbidden_field(path: str) -> None:
    document = generated()
    schema = document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]
    names = property_names(schema["schema"], document["components"]["schemas"])
    assert names and not names & FORBIDDEN_FIELDS


def test_model_output_is_declared_uncalibrated_and_readiness_never_claims_validation() -> None:
    schemas = generated()["components"]["schemas"]
    assert schemas["ModelOutput"]["properties"]["score_semantics"]["const"] == (
        "uncalibrated_softmax"
    )
    status = schemas["SmsModelStatus"]["properties"]
    assert status["validated_on_kavach_data"]["const"] is False
    assert status["score_semantics"]["const"] == "uncalibrated_softmax"


@pytest.mark.parametrize("path", ["/api/v1/incidents", "/api/v1/incidents/{incident_id}"])
def test_incident_errors_use_the_documented_envelope(path: str) -> None:
    document = generated()
    responses = document["paths"][path]["get"]["responses"]
    assert "default" in responses
    for status, response in responses.items():
        if status == "200":
            continue
        ref = response["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/ErrorResponse"), (path, status)
    envelope = document["components"]["schemas"]["ErrorResponse"]
    assert set(envelope["properties"]) == {"error", "request_id"}
    assert set(document["components"]["schemas"]["ErrorBody"]["properties"]) == {
        "code",
        "message",
    }


def mvp_examples() -> list[dict[str, Any]]:
    text = API_MD.read_text()
    section = text[text.index(MVP_SECTION) :]
    section = section[: section.index("\n## ", len(MVP_SECTION))]
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)```", section, re.S)]


def keys_of(value: Any, prefix: str = "") -> set[str]:
    """Dotted key paths of a JSON value (lists contribute their first element's keys)."""
    if isinstance(value, dict):
        found = set()
        for key, item in value.items():
            path = f"{prefix}{key}"
            found |= {path} | keys_of(item, f"{path}.")
        return found
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return keys_of(value[0], prefix)
    return set()


@pytest.mark.parametrize(
    ("index", "model"),
    [(0, IncidentListResponse), (1, IncidentDetailResponse), (2, AdminReceiptResponse)],
)
def test_the_api_md_examples_have_exactly_the_response_fields(index: int, model: type) -> None:
    example = mvp_examples()[index]
    # The example is valid against the DTO once placeholders get real values...
    filled = json.loads(
        re.sub(
            r'"(…|<uuid>|<opaque or null>|<model version>)"',
            fill,
            json.dumps(example, ensure_ascii=False),
        )
    )
    if "page" in filled:
        filled["page"]["next_cursor"] = None
    instance = model.model_validate(filled)
    # ...and the DTO serializes back to exactly the documented field set.
    assert keys_of(instance.model_dump(mode="json")) == keys_of(example)


def fill(match: re.Match[str]) -> str:
    return {
        "…": '"2031-01-01T12:00:00Z"',
        "<uuid>": '"00000000-0000-4000-8000-000000000000"',
        "<opaque or null>": "null",
        "<model version>": '"horizon-phishing-scam-base@test"',
    }[match.group(1)]


# --- MVP-B4: the submission route ----------------------------------------------------------------

# Receipts legitimately carry `source` and `external_event_id`; content and scores never.
RECEIPT_FORBIDDEN = {
    "text",
    "sender_id",
    "subscriber_token",
    "subscriber_digest",
    "payload_digest",
    "labels",
    "model_output",
    "sms_score",
    "final_score",
}


def sms_operation() -> tuple[dict[str, Any], dict[str, Any]]:
    document = generated()
    return document["paths"]["/api/v1/events/sms"]["post"], document["components"]["schemas"]


def test_the_sms_route_returns_either_receipt_and_only_the_admin_one_has_incidents() -> None:
    operation, schemas = sms_operation()
    for status in ("200", "201"):
        options = operation["responses"][status]["content"]["application/json"]["schema"]
        refs = {option["$ref"].rsplit("/", 1)[-1] for option in options["anyOf"]}
        assert refs == {"ReceiptResponse", "AdminReceiptResponse"}, status
    assert "incident_ids" not in schemas["EventReceipt"]["properties"]
    assert schemas["AdminEventReceipt"]["properties"]["incident_ids"]["type"] == "array"
    for name in ("ReceiptResponse", "AdminReceiptResponse"):
        names = property_names(schemas[name], schemas)
        assert not names & RECEIPT_FORBIDDEN, name


def test_the_sms_route_documents_its_body_and_every_error_with_the_envelope() -> None:
    operation, _ = sms_operation()
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert {"event_id", "subscriber_token", "timestamp", "source", "text"} <= set(
        body["properties"]
    )
    assert body["additionalProperties"] is False
    errors = {s for s in operation["responses"] if s not in ("200", "201")}
    assert errors == {"401", "403", "409", "413", "422", "429", "503", "default"}
    for status in errors:
        ref = operation["responses"][status]["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/ErrorResponse"), status


def test_the_call_route_and_receipt_reads_stay_key_only_and_unchanged() -> None:
    paths = generated()["paths"]
    call = paths["/api/v1/events/call"]["post"]["responses"]["201"]["content"]
    assert call["application/json"]["schema"]["$ref"].endswith("/ReceiptResponse")
    read = paths["/api/v1/events/{event_id}"]["get"]["responses"]["200"]["content"]
    assert read["application/json"]["schema"]["$ref"].endswith("/ReceiptResponse")
