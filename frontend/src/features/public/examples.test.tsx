// The login-free examples page: recorded results only, labelled as such, no way to submit text.
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiError } from "../../test/fakeFetch";
import { renderApp } from "../../test/renderApp";
import { RECORDED } from "./examples";

const signedOut = [() => apiError(401, "SESSION_EXPIRED")];
const NAMES: Record<string, string> = { fraud: "Fraud", spam: "Spam", legitimate: "Legitimate" };

describe("recorded examples page", () => {
  it("shows each recorded example with its prediction and native scores, in order", async () => {
    renderApp("/examples", signedOut);
    expect(
      await screen.findByRole("heading", { level: 1, name: "What the model said about fictional messages" }),
    ).toBeInTheDocument();
    const cards = within(screen.getByRole("list", { name: "Recorded examples" })).getAllByRole("article");
    expect(cards).toHaveLength(RECORDED.examples.length);
    RECORDED.examples.forEach((example, index) => {
      const card = cards[index];
      expect(card).toBeDefined();
      if (card === undefined) return;
      expect(within(card).getByText(example.text)).toBeInTheDocument();
      expect(within(card).getByText(/Recorded prediction:/)).toHaveTextContent(
        `Recorded prediction: ${NAMES[example.prediction] ?? "?"}`,
      );
      for (const [name, value] of Object.entries(example.labels)) {
        expect(card).toHaveTextContent(`${NAMES[name] ?? name} score${value.toFixed(4)}`);
      }
    });
  });

  it("says plainly that it is not live analysis and gives no way to submit text", async () => {
    const { container, requests } = renderApp("/examples", signedOut);
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByText(/recorded examples, not live analysis/i)).toBeInTheDocument();
    expect(screen.getByText(/no box to type a message into/)).toBeInTheDocument();
    expect(screen.getByText(RECORDED.model_version)).toBeInTheDocument();
    expect(screen.getByText(/not probabilities and not a risk level/)).toBeInTheDocument();
    expect(screen.getByText(/not validated on KAVACH data/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Want to try your own message?" })).toBeInTheDocument();
    // Nothing that could take input, and nothing that talks to the server.
    expect(container.querySelector("input, textarea, select, form, [contenteditable]")).toBeNull();
    expect(requests).toHaveLength(0);
    expect([window.localStorage.length, window.sessionStorage.length]).toEqual([0, 0]);
  });

  it("only ever shows fictional messages", () => {
    for (const example of RECORDED.examples) {
      expect(example.text.startsWith("FICTIONAL TEST:")).toBe(true);
    }
  });
});
