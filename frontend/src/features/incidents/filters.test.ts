import { describe, expect, it } from "vitest";

import {
  DEFAULT_FILTERS,
  PAGE_SIZE,
  filtersFromParams,
  filtersToParams,
  filtersToQuery,
  isFiltered,
  isoToLocalInput,
  localInputToIso,
  rangeError,
} from "./filters";

describe("incident filters", () => {
  it("defaults to SMS with no other filter and sends the documented query", () => {
    const filters = filtersFromParams(new URLSearchParams());
    expect(filters).toEqual(DEFAULT_FILTERS);
    expect(filtersToQuery(filters)).toEqual({ limit: PAGE_SIZE, channel: "sms" });
    expect(isFiltered(filters)).toBe(false);
  });

  it("round-trips valid filters through the URL", () => {
    const params = new URLSearchParams(
      "channel=call&kind=standalone&tier=unknown&from=2031-01-01T00:00:00Z&to=2031-01-02T00:00:00%2B05:30",
    );
    const filters = filtersFromParams(params);
    expect(filters).toEqual({
      channel: "call",
      kind: "standalone",
      tier: "unknown",
      from: "2031-01-01T00:00:00.000Z",
      to: "2031-01-01T18:30:00.000Z",
    });
    expect(filtersFromParams(filtersToParams(filters))).toEqual(filters);
    expect(filtersToQuery(filters, "c1")).toEqual({
      limit: PAGE_SIZE,
      channel: "call",
      kind: "standalone",
      tier: "unknown",
      from: "2031-01-01T00:00:00.000Z",
      to: "2031-01-01T18:30:00.000Z",
      cursor: "c1",
    });
  });

  it("drops unknown or malformed URL values instead of sending them", () => {
    const filters = filtersFromParams(
      new URLSearchParams(
        "channel=email&kind=triple&tier=severe&from=yesterday&to=2031-01-01T00:00:00&review_status=unreviewed",
      ),
    );
    expect(filters).toEqual(DEFAULT_FILTERS);
    expect(Object.keys(filtersToQuery(filters))).not.toContain("review_status");
  });

  it("omits the channel for 'all channels'", () => {
    expect(filtersToQuery({ ...DEFAULT_FILTERS, channel: "all" })).toEqual({ limit: PAGE_SIZE });
  });

  it("converts datetime-local values to RFC 3339 UTC and back", () => {
    const iso = localInputToIso("2031-03-04T05:06");
    // UTC with an explicit Z, whatever the viewer's zone (offsets can shift minutes too).
    expect(iso).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00\.000Z$/);
    expect(Date.parse(iso ?? "")).toBe(new Date(2031, 2, 4, 5, 6).getTime());
    expect(isoToLocalInput(iso)).toBe("2031-03-04T05:06");
    expect(localInputToIso("")).toBeNull();
    expect(localInputToIso("not a date")).toBeNull();
    expect(isoToLocalInput(null)).toBe("");
  });

  it("requires the start to be before the end", () => {
    expect(rangeError("2031-01-02T00:00:00Z", "2031-01-01T00:00:00Z")).toMatch(/before/);
    expect(rangeError("2031-01-01T00:00:00Z", "2031-01-01T00:00:00Z")).toMatch(/before/);
    expect(rangeError("2031-01-01T00:00:00Z", "2031-01-02T00:00:00Z")).toBeNull();
    expect(rangeError(null, "2031-01-02T00:00:00Z")).toBeNull();
  });
});
