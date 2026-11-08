// Fails the build if the production bundle contains credential material, browser-storage use,
// absolute API origins or test code (FRONTEND_MVP1_PLAN.md sections 10 and 11).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../dist/", import.meta.url));
const forbidden = [
  ["ingestion key prefix", /kvk_/],
  ["Authorization header", /\bAuthorization\b/],
  ["Bearer credential", /Bearer /],
  ["localStorage", /\blocalStorage\b/],
  ["sessionStorage", /\bsessionStorage\b/],
  ["absolute API origin", /https?:\/\/[^"'\s]*\/api\//],
  ["loopback backend address", /127\.0\.0\.1:8000/],
  ["test module", /src\/test\/|__tests__|fakeFetch/],
];

function files(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? files(path) : [path];
  });
}

const found = [];
for (const path of files(root)) {
  if (!/\.(js|css|html)$/.test(path)) continue;
  const text = readFileSync(path, "utf8");
  for (const [label, pattern] of forbidden) {
    if (pattern.test(text)) found.push(`${label}: ${path.slice(root.length)}`);
  }
}
if (found.length > 0) {
  console.error(`bundle scan failed:\n${found.join("\n")}`);
  process.exit(1);
}
console.log(`bundle scan passed (${files(root).length} files)`);
