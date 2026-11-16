// Finishes the static (browser-inference) build in dist/: self-hosts the ONNX Runtime WebAssembly
// files the page loads (never a third-party CDN) and adds 404.html so deep links such as
// /analyze load the single-page app on static hosts without rewrites. Model weights are not
// copied: the page downloads them from the pinned Hugging Face revision and verifies them.
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { join } from "node:path";

const dist = "dist";
const ort = join("node_modules", "onnxruntime-web", "dist");
mkdirSync(join(dist, "ort"), { recursive: true });
const runtime = readdirSync(ort).filter((name) => /^ort-wasm-simd-threaded(\.jsep|\.asyncify)?\.(mjs|wasm)$/.test(name));
for (const name of runtime) copyFileSync(join(ort, name), join(dist, "ort", name));
copyFileSync(join(dist, "index.html"), join(dist, "404.html"));
console.log(`static extras: ${String(runtime.length)} runtime files, 404.html`);
