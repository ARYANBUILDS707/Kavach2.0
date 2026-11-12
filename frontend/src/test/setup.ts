// TEST ONLY: Vitest setup. Runtime code never imports from src/test (lint rule).
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
