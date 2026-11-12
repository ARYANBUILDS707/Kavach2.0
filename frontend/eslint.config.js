import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// Project rules (FRONTEND_MVP1_PLAN.md section 10): no browser storage, no raw HTML, no
// Math.random, no console output, and runtime code never imports test code.
const projectRules = {
  "no-console": "error",
  "@typescript-eslint/no-explicit-any": "error",
  "no-restricted-globals": [
    "error",
    { name: "localStorage", message: "No browser storage (privacy rules)." },
    { name: "sessionStorage", message: "No browser storage (privacy rules)." },
    { name: "indexedDB", message: "No browser storage (privacy rules)." },
  ],
  "no-restricted-properties": [
    "error",
    { object: "window", property: "localStorage", message: "No browser storage." },
    { object: "window", property: "sessionStorage", message: "No browser storage." },
    { object: "window", property: "indexedDB", message: "No browser storage." },
    { object: "Math", property: "random", message: "Use crypto.getRandomValues/randomUUID." },
  ],
  "no-restricted-syntax": [
    "error",
    {
      selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
      message: "Render text through React; raw HTML is not allowed.",
    },
  ],
};

export default tseslint.config(
  { ignores: ["dist", "node_modules", "coverage", "playwright-report", "test-results"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        project: ["./tsconfig.json", "./tsconfig.node.json"],
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    // Plain JavaScript (this config and the node scripts) is linted without type information.
    files: ["**/*.js", "**/*.mjs"],
    ...tseslint.configs.disableTypeChecked,
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...projectRules,
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            { group: ["**/test/**", "**/__tests__/**"], message: "Runtime code must not import tests." },
          ],
        },
      ],
    },
  },
  {
    // Tests may import test helpers and read browser storage to prove it stays empty; the
    // Math.random ban and every other project rule still apply.
    files: ["src/**/*.test.{ts,tsx}", "src/test/**"],
    rules: {
      "no-restricted-imports": "off",
      "no-restricted-properties": [
        "error",
        { object: "Math", property: "random", message: "Use crypto.getRandomValues/randomUUID." },
      ],
    },
  },
  {
    files: ["scripts/**/*.mjs", "*.config.{js,ts}", "tests/**/*.ts"],
    languageOptions: { globals: globals.node },
    rules: { "no-console": "off" },
  },
);
