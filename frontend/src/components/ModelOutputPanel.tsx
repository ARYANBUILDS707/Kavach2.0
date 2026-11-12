// Native model outputs (FRONTEND_MVP1_PLAN.md section 8, non-negotiable): a plain table of the
// three labels at 4 decimals, no percentages, bars, gauges or colour scale, always labelled as
// uncalibrated and unvalidated. The top label is stated as the model's experimental prediction,
// never as a finding about the message.
import { useId } from "react";

import { NOT_AVAILABLE, formatModelValue } from "../lib/format";
import type { ModelOutput } from "../lib/api/types";

const LABEL_ORDER = ["legitimate", "spam", "fraud"];
const PREDICTION_NAMES: Record<string, string> = {
  legitimate: "Legitimate",
  spam: "Spam",
  fraud: "Fraud",
};

function renderValue(value: number | undefined): string {
  return value === undefined ? NOT_AVAILABLE : formatModelValue(value);
}

export function ModelOutputPanel({
  output,
  modelVersion,
}: {
  output: ModelOutput;
  modelVersion: string | null;
}) {
  const headingId = useId();
  const names = [
    ...LABEL_ORDER.filter((name) => name in output.labels),
    ...Object.keys(output.labels).filter((name) => !LABEL_ORDER.includes(name)),
  ];
  return (
    <section className="model-output" aria-labelledby={headingId}>
      <h4 id={headingId}>Model prediction (experimental)</h4>
      <p className="model-prediction">
        The model predicts: <strong>{PREDICTION_NAMES[output.top_label] ?? output.top_label}</strong>
      </p>
      <p>
        This is a prediction from the pinned experimental model, not an established fact. The model
        is not validated on KAVACH data; a person decides what the message is.
      </p>
      <p>Native scores below are uncalibrated: not probabilities and not a risk score.</p>
      <table className="compact-table">
        <caption className="visually-hidden">Native model output by label</caption>
        <thead>
          <tr>
            <th scope="col">Label</th>
            <th scope="col">Native score</th>
          </tr>
        </thead>
        <tbody>
          {names.map((name) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              <td className="numeric">{renderValue(output.labels[name])}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {output.truncated ? (
        <p>The message was longer than the model reads; only the first part was scored.</p>
      ) : null}
      <p className="shell-meta">
        Model version: <span className="copyable-id">{modelVersion ?? NOT_AVAILABLE}</span> ·
        Score semantics: uncalibrated softmax
      </p>
    </section>
  );
}
