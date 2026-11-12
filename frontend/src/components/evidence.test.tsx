import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CALL_EVENT, UNAVAILABLE_SMS_EVENT, detail } from "../test/fixtures";
import { RiskBadge } from "./Badges";
import { ModelOutputPanel } from "./ModelOutputPanel";
import { StageList } from "./StageList";

function completeOutput() {
  const output = detail().events[0]?.stages.sms_classifier?.model_output;
  if (output === undefined || output === null) throw new Error("fixture has no model output");
  return output;
}

const OUTPUT = completeOutput();

describe("ModelOutputPanel", () => {
  it("shows native scores to 4 decimals, the prediction and the uncalibrated warning", () => {
    render(<ModelOutputPanel output={OUTPUT} modelVersion="horizon-phishing-scam-base@test" />);
    expect(screen.getByRole("heading", { name: "Model prediction (experimental)" })).toBeInTheDocument();
    expect(screen.getByText(/The model predicts:/)).toHaveTextContent("The model predicts: Fraud");
    expect(screen.getByText(/not an established fact/)).toBeInTheDocument();
    expect(screen.getByText(/not probabilities and not a risk score/)).toBeInTheDocument();
    expect(screen.getByText(/not validated on KAVACH data/)).toBeInTheDocument();
    const table = screen.getByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "legitimate0.1234",
      "spam0.0567",
      "fraud0.8199",
    ]);
    expect(screen.getByText("Fraud", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("horizon-phishing-scam-base@test")).toBeInTheDocument();
  });

  it("never shows a percentage, a progress bar or a meter", () => {
    const { container } = render(<ModelOutputPanel output={OUTPUT} modelVersion={null} />);
    expect(container.textContent).not.toContain("%");
    expect(container.querySelector("progress, meter, [role=progressbar], [role=meter]")).toBeNull();
    expect(screen.getByText("Not available")).toBeInTheDocument();
  });

  it("notes truncation and never turns a missing label into 0", () => {
    render(
      <ModelOutputPanel
        output={{ ...OUTPUT, truncated: true, labels: { legitimate: 0.5 } }}
        modelVersion={null}
      />,
    );
    expect(screen.getByText(/only the first part was scored/)).toBeInTheDocument();
    expect(screen.queryByText("0.0000")).toBeNull();
  });
});

describe("StageList", () => {
  it("names an unavailable stage, its reason and that it is not treated as safe", () => {
    render(<StageList stages={UNAVAILABLE_SMS_EVENT.stages} modelVersions={{}} />);
    expect(screen.getByRole("heading", { name: "SMS classifier" })).toBeInTheDocument();
    expect(screen.getByText("Model not enabled")).toBeInTheDocument();
    expect(screen.getByText(/not treated as safe/)).toBeInTheDocument();
    expect(screen.queryByText(/Model output/)).toBeNull();
  });

  it("shows every voice stage of a metadata-only call as unavailable", () => {
    render(<StageList stages={CALL_EVENT.stages} modelVersions={{}} />);
    for (const name of ["Transcription", "Voice intent", "Synthetic-speech indication"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getAllByText("No audio provided")).toHaveLength(3);
  });

  it("shows an unknown reason code as the code, not as a guess", () => {
    render(
      <StageList
        stages={{ sms_classifier: { status: "unavailable", reason: "new_reason", duration_ms: 3, model_output: null } }}
        modelVersions={{}}
      />,
    );
    expect(screen.getByText("Unavailable (new_reason)")).toBeInTheDocument();
  });
});

describe("RiskBadge", () => {
  it("states that an unknown tier has no calibrated signal, as text", () => {
    render(<RiskBadge tier="unknown" />);
    expect(screen.getByText("Risk tier: Unknown (no calibrated signal)")).toBeInTheDocument();
  });
});
