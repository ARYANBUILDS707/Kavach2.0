/** In-browser inference with the pinned SMS classifier (static build only, decision C-16).
 *
 * The model is the upstream authors' own ONNX export (int8 embeddings) of exactly the revision the
 * server worker uses, downloaded from Hugging Face at that revision. Every file is checked against
 * the size and SHA-256 published in the upstream SHA256SUMS before the runtime sees it; any other
 * URL is refused, so neither the library nor message content can make the page fetch anything
 * else. The SMS text never leaves this function: tokenization and inference run on the device. */
import type { PreTrainedModel, PreTrainedTokenizer, Tensor } from "@huggingface/transformers";

export const MODEL_REPO = "Horizon-Labs/phishing-scam-detector-base";
export const MODEL_REVISION = "fa686fc0d6a3634092ada93a7c6b89ab0746b8f8";
export const MODEL_VERSION = "horizon-phishing-scam-base@fa686fc0d6a3+onnx-q8";
const LABELS = ["legitimate", "spam", "fraud"] as const;
export type Label = (typeof LABELS)[number];
// The worker truncates at the same token count (manifest preprocessing.max_tokens).
const MAX_TOKENS = 256;

export const MODEL_FILES: Readonly<Record<string, { size: number; sha256: string }>> = {
  "config.json": { size: 2068, sha256: "99b40411e6748ebc586843956cd36377fc928f2d743395f136a9a15ce464daa9" },
  "tokenizer.json": { size: 34363286, sha256: "e7322a5d841fcfe921a2457104f85e5bfd2fbb03cdbbe495ce6c04365b9f670a" },
  "tokenizer_config.json": { size: 46440, sha256: "1d2f82c1341a79748e00efe82e67690f99d00b3c2a894f2b23128fd9d3519da3" },
  "special_tokens_map.json": { size: 636, sha256: "baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351" },
  "onnx/model_quantized.onnx": { size: 641128988, sha256: "93b2e8e547770b940bba9776dc9139fcacc02c98589bf32eb181025cc76509e0" },
};
export const DOWNLOAD_BYTES = Object.values(MODEL_FILES).reduce((sum, file) => sum + file.size, 0);
const RESOLVE_PREFIX = `https://huggingface.co/${MODEL_REPO}/resolve/${MODEL_REVISION}/`;

export interface BrowserPrediction { prediction: Label; truncated: boolean; model_ms: number }
export type Progress = (loadedBytes: number, totalBytes: number) => void;

function hex(buffer: ArrayBuffer): string {
  return Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

/** Download one pinned file with progress and refuse it unless size and SHA-256 match. */
export async function verifiedDownload(
  name: string, fetcher: typeof fetch, onBytes: (bytes: number) => void,
): Promise<Uint8Array<ArrayBuffer>> {
  const expected = MODEL_FILES[name];
  if (expected === undefined) throw new Error("Refused an unpinned model file.");
  const response = await fetcher(RESOLVE_PREFIX + name, { credentials: "omit", referrerPolicy: "no-referrer" });
  if (!response.ok || response.body === null) throw new Error("Model download failed. Check your connection and retry.");
  const bytes = new Uint8Array(new ArrayBuffer(expected.size));
  let offset = 0;
  const reader = response.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    if (offset + value.byteLength > expected.size) throw new Error("Model file is larger than the pinned size; refused.");
    bytes.set(value, offset);
    offset += value.byteLength;
    onBytes(value.byteLength);
  }
  if (offset !== expected.size) throw new Error("Model download was incomplete. Retry.");
  if (hex(await crypto.subtle.digest("SHA-256", bytes)) !== expected.sha256) {
    throw new Error("Model file failed its integrity check; refused.");
  }
  return bytes;
}

interface Loaded { tokenizer: PreTrainedTokenizer; model: PreTrainedModel }
let loading: Promise<Loaded> | null = null;

/** Load once per page. Progress counts verified-download bytes across all files. */
export function loadModel(onProgress: Progress, fetcher: typeof fetch = fetch.bind(globalThis)): Promise<Loaded> {
  loading ??= (async () => {
    const transformers = await import("@huggingface/transformers");
    const { env, AutoTokenizer, AutoModelForSequenceClassification } = transformers;
    let loaded = 0;
    env.allowLocalModels = false;
    // The library falls back to `main` for some files even when given `revision`; pin the
    // template itself so every request names the pinned commit (env.fetch refuses anything else).
    env.remotePathTemplate = `{model}/resolve/${MODEL_REVISION}/`;
    // Self-hosted runtime; never a third-party CDN.
    const wasm = env.backends.onnx.wasm;
    if (wasm !== undefined) wasm.wasmPaths = `${import.meta.env.BASE_URL}ort/`;
    env.fetch = async (input: string | URL) => {
      const url = String(input);
      if (!url.startsWith(RESOLVE_PREFIX)) return new Response(null, { status: 404 });
      const name = decodeURIComponent(url.slice(RESOLVE_PREFIX.length).split("?")[0] ?? "");
      if (MODEL_FILES[name] === undefined) return new Response(null, { status: 404 });
      const bytes = await verifiedDownload(name, fetcher, (count) => {
        loaded += count;
        onProgress(loaded, DOWNLOAD_BYTES);
      });
      return new Response(bytes, { status: 200, headers: { "Content-Length": String(bytes.byteLength) } });
    };
    const options = { revision: MODEL_REVISION };
    const tokenizer = await AutoTokenizer.from_pretrained(MODEL_REPO, options);
    const model = await AutoModelForSequenceClassification.from_pretrained(MODEL_REPO, {
      ...options, dtype: "q8", device: "wasm",
    });
    const labels = (model.config as unknown as { id2label?: Record<string, string> }).id2label;
    if (labels === undefined || LABELS.some((label, index) => labels[String(index)] !== label)) {
      throw new Error("Model labels differ from the pinned model; refused.");
    }
    return { tokenizer, model };
  })();
  loading.catch(() => { loading = null; });
  return loading;
}

/** Classify on the device. Returns the class only: native scores are uncalibrated. */
export async function classify(loaded: Loaded, text: string): Promise<BrowserPrediction> {
  const started = performance.now();
  const full = loaded.tokenizer(text, { truncation: false }) as { input_ids: Tensor };
  const inputs = loaded.tokenizer(text, { truncation: true, max_length: MAX_TOKENS });
  const { logits } = (await loaded.model(inputs)) as { logits: Tensor };
  const values = Array.from(logits.data as Float32Array);
  const top = values.indexOf(Math.max(...values));
  const prediction = LABELS[top];
  if (prediction === undefined || values.length !== LABELS.length) throw new Error("Unexpected model output.");
  return {
    prediction,
    truncated: Number(full.input_ids.dims.at(-1)) > MAX_TOKENS,
    model_ms: Math.round(performance.now() - started),
  };
}
