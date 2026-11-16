import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BrowserAnalyzerPage } from "./BrowserAnalyzerPage";

afterEach(() => { vi.unstubAllGlobals(); });

function setup() {
  const fetcher = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter><BrowserAnalyzerPage /></MemoryRouter>);
  return fetcher;
}

describe("browser analyzer page", () => {
  it("leads with the checker and keeps the material risks visible", () => {
    const fetcher = setup();
    expect(screen.getByRole("heading", { level: 1, name: "Is this SMS a scam?" })).toBeInTheDocument();
    expect(screen.getByLabelText("SMS to analyze")).toBeEnabled();
    expect(screen.getByText(/First use downloads the AI model once \(\d+ MB\)/)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /experimental, unvalidated prediction/ })).not.toBeChecked();
    expect(screen.getByText(/How it works, privacy & limitations/)).toBeInTheDocument();
    expect(screen.queryByText(/fictional messages only/i)).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("samples only fill the input; nothing is predicted or downloaded without the model", () => {
    const fetcher = setup();
    fireEvent.click(screen.getByRole("button", { name: "Try Fraud Example" }));
    expect(screen.getByLabelText("SMS to analyze")).toHaveValue(
      "Your Northpay account is frozen. Confirm your PIN at the link now to avoid closure.");
    // Consent is required before the analysis (and the download it starts) can begin.
    expect(screen.getByRole("button", { name: "Analyze SMS" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: /experimental, unvalidated prediction/ }));
    expect(screen.getByRole("button", { name: "Analyze SMS" })).toBeEnabled();
    expect(screen.queryByRole("heading", { name: /Prediction:/ })).not.toBeInTheDocument();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
