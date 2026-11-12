// Display rules (FRONTEND_MVP1_PLAN.md section 8, DESIGN.md typography): explicit text for every
// enum, "Not available" for null, model scores as plain 4-decimal numbers (never percentages).
import type { AnalysisStatus, Channel, IncidentKind, ModelState, Tier } from "./api/types";

export const NOT_AVAILABLE = "Not available";

export const TIER_LABELS: Record<Tier, string> = {
  unknown: "Unknown",
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const ANALYSIS_LABELS: Record<AnalysisStatus, string> = {
  complete: "Complete",
  partial: "Partial",
  unavailable: "Unavailable",
};

export const KIND_LABELS: Record<IncidentKind, string> = {
  standalone: "Standalone",
  pair: "Pair",
};

export const CHANNEL_LABELS: Record<Channel, string> = { sms: "SMS", call: "Call" };

export const MODEL_STATE_LABELS: Record<ModelState, string> = {
  ready: "Ready",
  starting: "Starting",
  disabled: "Disabled",
  unavailable: "Unavailable",
};

export const STAGE_LABELS: Record<string, string> = {
  sms_classifier: "SMS classifier",
  transcription: "Transcription",
  voice_intent: "Voice intent",
  synthesis: "Synthetic-speech indication",
};

const REASON_LABELS: Record<string, string> = {
  model_not_deployed: "Model not enabled",
  model_unverified: "Model files failed verification",
  worker_unavailable: "Model worker unavailable",
  inference_timeout: "Model timed out",
  worker_crashed: "Model worker stopped",
  invalid_model_output: "Model returned an invalid result",
  deadline_exhausted: "Request deadline reached",
  audio_not_provided: "No audio provided",
};

const REASON_CODE_LABELS: Record<string, string> = {
  sms_model_uncalibrated: "SMS model output is uncalibrated",
};

export function stageLabel(name: string): string {
  return STAGE_LABELS[name] ?? name;
}

/** Known reason codes get plain text; anything else is shown with its code. */
export function reasonLabel(reason: string | null): string {
  if (reason === null) return NOT_AVAILABLE;
  return REASON_LABELS[reason] ?? `Unavailable (${reason})`;
}

export function reasonCodeLabel(code: string): string {
  return REASON_CODE_LABELS[code] ?? code;
}

/** A nullable score: "Not available" for null, never 0 and never "safe". */
export function formatScore(value: number | null | undefined): string {
  return value === null || value === undefined ? NOT_AVAILABLE : value.toFixed(4);
}

/** Native model output: 4 decimals, no percent sign. */
export function formatModelValue(value: number): string {
  return value.toFixed(4);
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

const LOCAL_FORMAT = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  timeZoneName: "short",
});

/** Local display with time zone; the exact UTC value is returned separately for a11y. */
export function formatTimestamp(iso: string): { local: string; utc: string } {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return { local: iso, utc: iso };
  return { local: LOCAL_FORMAT.format(date), utc: date.toISOString() };
}

export function formatClockTime(epochMs: number): string {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(epochMs));
}
