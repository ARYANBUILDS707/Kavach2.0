import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicAnalyzerPage } from "./PublicAnalyzerPage";

const reply = (data: unknown, status = 200) => new Response(JSON.stringify({ data }), { status });
afterEach(() => { vi.unstubAllGlobals(); });
function setup(enabled = true) {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValueOnce(reply({ enabled, max_chars: 500 }));
  vi.stubGlobal("fetch", fetcher);
  render(<MemoryRouter><PublicAnalyzerPage /></MemoryRouter>);
  return fetcher;
}
describe("anonymous analyzer", () => {
  it("shows disabled without submitting or looking up a session", async () => {
    const fetcher = setup(false);
    await screen.findByText(/Public analysis is disabled/);
    expect(screen.getByRole("button", { name: "Analyze" })).toBeDisabled();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/v1/public/analyzer");
  });
  it("submits once without cookies, shows actual response and clears input", async () => {
    const fetcher = setup();
    const input = await screen.findByLabelText("Fictional SMS");
    await vi.waitFor(() => { expect(input).toBeEnabled(); });
    fireEvent.change(input, { target: { value: "FICTIONAL TEST: dinner" } });
    fetcher.mockResolvedValueOnce(reply({ prediction: "legitimate", experimental: true,
      truncated: true, model_ms: 12, total_ms: 14 }));
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await screen.findByRole("heading", { name: "Prediction: Legitimate" });
    expect(input).toHaveValue("");
    expect(screen.getByText(/model truncated/)).toBeInTheDocument();
    expect(fetcher.mock.calls[1]?.[1]?.credentials).toBe("omit");
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
    fireEvent.change(input, { target: { value: "edited" } });
    expect(screen.queryByRole("heading", { name: /Prediction:/ })).not.toBeInTheDocument();
  });
  it.each([429, 503, 403, 422])("handles HTTP %s without inventing a prediction", async (status) => {
    const fetcher = setup();
    const input = await screen.findByLabelText("Fictional SMS");
    await vi.waitFor(() => { expect(input).toBeEnabled(); });
    fireEvent.change(input, { target: { value: "FICTIONAL TEST: dinner" } });
    fetcher.mockResolvedValueOnce(reply({}, status));
    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    await screen.findByRole("alert");
    expect(input).toHaveValue("FICTIONAL TEST: dinner");
    expect(screen.queryByRole("heading", { name: /Prediction:/ })).not.toBeInTheDocument();
  });
});
