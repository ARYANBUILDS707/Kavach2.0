import { describe, expect, it } from "vitest";

import { loginPath, safeNext } from "./routes";

describe("safeNext", () => {
  it.each([
    ["/", "/"],
    ["/incidents", "/incidents"],
    ["/incidents?tier=unknown&from=2031-01-01T00%3A00%3A00Z", "/incidents?tier=unknown&from=2031-01-01T00%3A00%3A00Z"],
    ["/incidents/00000000-0000-4000-8000-000000000001", "/incidents/00000000-0000-4000-8000-000000000001"],
    ["/system", "/system"],
  ])("keeps the internal path %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });

  it.each([
    null,
    "https://evil.test/",
    "//evil.test",
    "/\\evil.test",
    "javascript:alert(1)",
    "/login",
    "/unknown",
    "/incidents/not-a-uuid",
    "/incidents?<script>",
    "/incidents?" + "a".repeat(600),
  ])("falls back to the start page for %s", (input) => {
    expect(safeNext(input)).toBe("/");
  });

  it("builds the login path with an encoded next only when needed", () => {
    expect(loginPath("/")).toBe("/login");
    expect(loginPath("/system")).toBe("/login?next=%2Fsystem");
  });
});
