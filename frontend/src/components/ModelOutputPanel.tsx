// Native model outputs (FRONTEND_MVP1_PLAN.md section 8, non-negotiable): a plain table of the
// three labels at 4 decimals, no percentages, bars, gauges or colour scale, always labelled as
// uncalibrated and unvalidated.
import { useId } from "react";

import { NOT_AVAILABLE, formatModelValue } from "../lib/format";
import type { ModelOutput } from "../lib/api/types";

const LABEL_ORDER = ["legitimate", "spam", "fraud"];

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
      <h4 id={headingId}>Model output (uncalibrated)</h4>
      <p>
        Native scores from the pinned experimental model. They are not probabilities, not a risk
        score, and the model is not validated on KAVACH data.
      </p>
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
      <p>
        Model&apos;s top label: <strong>{output.top_label}</strong>
      </p>
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
