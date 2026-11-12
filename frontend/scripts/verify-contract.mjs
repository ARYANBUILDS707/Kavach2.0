// Refuses to generate API types unless contract/openapi.json has the SHA-256 recorded in
// contract/SOURCE.md (the frozen backend snapshot and its source commit).
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const contract = new URL("../contract/openapi.json", import.meta.url);
const source = readFileSync(new URL("../contract/SOURCE.md", import.meta.url), "utf8");

const recorded = source.match(/\b[0-9a-f]{64}\b/g) ?? [];
const commit = source.match(/Source commit:\s*([0-9a-f]{40})/)?.[1];
if (new Set(recorded).size !== 1 || commit === undefined) {
  console.error("contract/SOURCE.md must record exactly one SHA-256 and the source commit");
  process.exit(1);
}
const actual = createHash("sha256").update(readFileSync(contract)).digest("hex");
if (actual !== recorded[0]) {
  console.error(`contract/openapi.json does not match SOURCE.md (got ${actual})`);
  process.exit(1);
}
console.log(`contract verified: sha256 ${actual} from backend commit ${commit}`);
