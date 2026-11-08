// TEST ONLY: synthetic records in the exact contract shapes, for component tests. They are never
// imported by runtime code (lint rule + bundle scan) and are not model predictions: the numbers
// below are arbitrary test values chosen to check formatting.
import type {
  IncidentDetail,
  IncidentEvent,
  IncidentSummary,
  SmsModelStatus,
} from "../lib/api/types";

export const INCIDENT_ID = "11111111-1111-4111-8111-111111111111";

export function summary(index: number, overrides: Partial<IncidentSummary> = {}): IncidentSummary {
  const id = `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`;
  return {
    id,
    kind: "standalone",
    occurred_at: `2031-01-01T12:${String(index % 60).padStart(2, "0")}:00Z`,
    tier: "unknown",
    final_score: null,
    analysis_status: "unavailable",
    current_revision: 1,
    version: 1,
    latest_review: null,
    updated_at: "2031-01-01T12:00:01Z",
    ...overrides,
  };
}

export function page(items: IncidentSummary[], nextCursor: string | null = null) {
  return {
    data: items,
    page: { next_cursor: nextCursor, has_more: nextCursor !== null },
    request_id: "req-list",
  };
}

const COMPLETE_SMS_EVENT: IncidentEvent = {
  id: "22222222-2222-4222-8222-222222222222",
  channel: "sms",
  occurred_at: "2031-01-01T12:00:00Z",
  received_at: "2031-01-01T12:00:02Z",
  analysis_status: "complete",
  processing_ms: 412,
  sms_score: null,
  reason_codes: ["sms_model_uncalibrated"],
  stages: {
    sms_classifier: {
      status: "complete",
      reason: null,
      duration_ms: 41,
      model_output: {
        labels: { legitimate: 0.1234, spam: 0.0567, fraud: 0.8199 },
        top_label: "fraud",
        score_semantics: "uncalibrated_softmax",
        truncated: false,
      },
    },
  },
  model_versions: { sms_classifier: "horizon-phishing-scam-base@test" },
};

export function detail(overrides: Partial<IncidentDetail> = {}): IncidentDetail {
  return {
    ...summary(1, { id: INCIDENT_ID, analysis_status: "partial" }),
    events: [COMPLETE_SMS_EVENT],
    assessment: {
      revision: 1,
      tier: "unknown",
      base_score: null,
      fusion_score: null,
      final_score: null,
      analysis_status: "partial",
      policy_version: "kavach-m4-uncalibrated-sms-evidence",
      model_versions: { sms_classifier: "horizon-phishing-scam-base@test" },
      created_at: "2031-01-01T12:00:02Z",
    },
    related_incident_ids: [],
    reviews: { items: [], page: { next_cursor: null, has_more: false } },
    ...overrides,
  };
}

export const UNAVAILABLE_SMS_EVENT: IncidentEvent = {
  ...COMPLETE_SMS_EVENT,
  id: "33333333-3333-4333-8333-333333333333",
  analysis_status: "unavailable",
  reason_codes: [],
  stages: {
    sms_classifier: { status: "unavailable", reason: "model_not_deployed", duration_ms: 0, model_output: null },
  },
  model_versions: {},
};

export const CALL_EVENT: IncidentEvent = {
  ...UNAVAILABLE_SMS_EVENT,
  id: "44444444-4444-4444-8444-444444444444",
  channel: "call",
  stages: {
    transcription: { status: "unavailable", reason: "audio_not_provided", duration_ms: 0, model_output: null },
    voice_intent: { status: "unavailable", reason: "audio_not_provided", duration_ms: 0, model_output: null },
    synthesis: { status: "unavailable", reason: "audio_not_provided", duration_ms: 0, model_output: null },
  },
};

export function models(state: SmsModelStatus["state"], overrides: Partial<SmsModelStatus> = {}) {
  return {
    data: {
      sms_classifier: {
        state,
        detail: state === "ready" ? "ready" : state === "unavailable" ? "circuit_open" : state,
        reason: state === "unavailable" ? "worker_crashed" : null,
        model_version: state === "disabled" ? null : "horizon-phishing-scam-base@test",
        score_semantics: "uncalibrated_softmax" as const,
        validated_on_kavach_data: false as const,
        ...overrides,
      },
    },
    request_id: "req-models",
  };
}
