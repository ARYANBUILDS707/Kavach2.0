import { describe, expect, it } from "vitest";

import { ADMIN_HOME, ADMIN_LOGIN, adminIncident, loginPath, safeNext } from "./routes";

describe("safeNext", () => {
  it.each([
    ["/admin", "/admin"],
    ["/admin/incidents", "/admin/incidents"],
    [
      "/admin/incidents?tier=unknown&from=2031-01-01T00%3A00%3A00Z",
      "/admin/incidents?tier=unknown&from=2031-01-01T00%3A00%3A00Z",
    ],
    [
      "/admin/incidents/00000000-0000-4000-8000-000000000001",
      "/admin/incidents/00000000-0000-4000-8000-000000000001",
    ],
    ["/admin/system", "/admin/system"],
    ["/admin/analyze", "/admin/analyze"],
  ])("keeps the console path %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });

  it.each([
    null,
    "https://evil.test/",
    "//evil.test",
    "/\\evil.test",
    "javascript:alert(1)",
    // Public pages and the old unprefixed console paths are not sign-in destinations.
    "/",
    "/examples",
    "/login",
    "/incidents",
    "/system",
    "/admin/login",
    "/admin/unknown",
    "/admin/../examples",
    "/admin/incidents/not-a-uuid",
    "/admin/incidents?<script>",
    "/admin/incidents?" + "a".repeat(600),
  ])("falls back to the console overview for %s", (input) => {
    expect(safeNext(input)).toBe(ADMIN_HOME);
  });

  it("builds the sign-in path with an encoded next only when needed", () => {
    expect(loginPath(ADMIN_HOME)).toBe(ADMIN_LOGIN);
    expect(loginPath("/admin/system")).toBe("/admin/login?next=%2Fadmin%2Fsystem");
  });

  it("builds incident paths under the console", () => {
    expect(adminIncident("abc")).toBe("/admin/incidents/abc");
  });
});
