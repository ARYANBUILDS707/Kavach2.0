import recorded from "./examples.json";

/** One fictional message with what the pinned model returned for it in a recorded local run. */
export interface RecordedExample {
  id: string;
  scenario: string;
  text: string;
  prediction: string;
  labels: Record<string, number>;
}

export interface RecordedExamples {
  recorded_on: string;
  model_version: string;
  examples: RecordedExample[];
}

// Re-recorded from real inference by backend/tests/test_public_examples.py (never edited by hand).
// The assignment is type-checked against the interface; nothing here is cast.
export const RECORDED: RecordedExamples = recorded;
