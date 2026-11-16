import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { BrowserAnalyzerPage } from "./BrowserAnalyzerPage";

afterEach(() => { vi.unstubAllGlobals(); });

describe("browser analyzer page", () => {
  it("makes no request and cannot analyze until the visitor loads the model", () => {
    const fetcher = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetcher);
    render(<MemoryRouter><BrowserAnalyzerPage /></MemoryRouter>);
    expect(screen.getByText(/not validated on KAVACH data/)).toBeInTheDocument();
    expect(screen.getByText(/stays on this device/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Load model \(\d+ MB\)$/ })).toBeEnabled();
    expect(screen.getByLabelText("Fictional SMS")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Fictional SMS"), { target: { value: "FICTIONAL" } });
    expect(screen.getByRole("button", { name: "Analyze" })).toBeDisabled();
    expect(fetcher).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: /Prediction:/ })).not.toBeInTheDocument();
  });
});
