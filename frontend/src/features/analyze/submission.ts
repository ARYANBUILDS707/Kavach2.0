// Submission rules for the admin SMS page (API.md "POST /api/v1/events/sms — admin browser path").
// A submission's identifiers and timestamp are created once and reused for every manual retry,
// so a retry can only replay (200) the same event, never silently create a second one.
import { ApiError, isApiError } from "../../lib/api/errors";
import type { SmsSubmission } from "../../lib/api/types";
import { browserEventId, browserSubscriberToken } from "../../lib/ids";

export const MAX_TEXT_CHARACTERS = 4096;

/** Characters as the server counts them (code points), not UTF-16 units. */
export function characterCount(text: string): number {
  return Array.from(text).length;
}

export function validateText(text: string): string | null {
  if (text.trim() === "") return "Enter the synthetic message text.";
  if (characterCount(text) > MAX_TEXT_CHARACTERS) {
    return `The message can have at most ${MAX_TEXT_CHARACTERS.toLocaleString("en")} characters.`;
  }
  return null;
}

export function newSubmission(text: string, now: () => Date = () => new Date()): SmsSubmission {
  return {
    event_id: browserEventId(),
    subscriber_token: browserSubscriberToken(),
    timestamp: now().toISOString(),
    source: "simulator",
    text,
  };
}

/**
 * `notStored`: the server refused before storing anything; editing is safe.
 * `uncertain`: the outcome is unknown (network, timeout, 5xx); only a retry with the SAME
 *   identifiers is offered, which returns the original receipt if it was stored.
 * `conflict`: the identifiers were already used with different content; start over.
 */
export type FailureKind = "notStored" | "uncertain" | "conflict" | "sessionEnded";

export interface Failure {
  kind: FailureKind;
  title: string;
  message: string;
  requestId: string | null;
  retryAfterSeconds: number | null;
}

function failure(
  kind: FailureKind,
  title: string,
  message: string,
  error: ApiError | null,
): Failure {
  return {
    kind,
    title,
    message,
    requestId: error?.requestId ?? null,
    retryAfterSeconds: error?.retryAfterSeconds ?? null,
  };
}

export function classifyFailure(error: unknown): Failure {
  if (!isApiError(error)) {
    return failure(
      "uncertain",
      "Outcome unknown",
      "Something went wrong before a receipt arrived. Retry to send the same submission again; if it was stored, you will get the original receipt.",
      null,
    );
  }
  const wait =
    error.retryAfterSeconds !== null ? ` Try again in ${String(error.retryAfterSeconds)} seconds.` : "";
  if (error.code === "NETWORK_ERROR" || error.code === "TIMEOUT" || error.status >= 500) {
    return failure(
      "uncertain",
      error.code === "TIMEOUT" ? "No answer in time" : "Outcome unknown",
      `We could not confirm whether the message was stored.${wait} Retry sends the same submission again: if it was stored, you will see the original receipt and no second record is created.`,
      error,
    );
  }
  switch (error.status) {
    case 401:
      return failure("sessionEnded", "Your session ended", "Sign in again to continue.", error);
    case 403:
      return error.code === "CSRF_REJECTED"
        ? failure(
            "notStored",
            "Request blocked for safety",
            "The request did not come from KAVACH's configured address or its security token was missing. Reload the page from the configured address and submit again. Nothing was stored.",
            error,
          )
        : failure(
            "notStored",
            "Not allowed",
            "Only admins can submit, and only as the simulator source. Nothing was stored.",
            error,
          );
    case 409:
      return failure(
        "conflict",
        "Already used with different content",
        "This submission's event ID was already used with a different message. Start a new submission. Nothing new was stored.",
        error,
      );
    case 413:
      return failure("notStored", "Message too large", "Shorten the message and try again. Nothing was stored.", error);
    case 422:
      return failure(
        "notStored",
        "The server rejected the message",
        "Check that the text is not blank and at most 4,096 characters, and that this computer's clock is correct. Nothing was stored.",
        error,
      );
    case 429:
      return failure(
        "notStored",
        error.code === "CAPACITY_EXCEEDED" ? "Analysis capacity is full" : "Too many submissions",
        `Nothing was stored.${wait} Submitting the same message again reuses the same submission.`,
        error,
      );
    default:
      return failure("notStored", "Submission failed", "The request could not be completed.", error);
  }
}

const WARNING_LABELS: Record<string, string> = {
  SMS_CLASSIFIER_UNAVAILABLE: "SMS model unavailable: stored without a model result",
  SMS_SCORE_UNCALIBRATED: "Model output is uncalibrated",
};

export function warningLabel(code: string): string {
  return WARNING_LABELS[code] ?? code;
}
