import { describe, expect, it, vi } from "vitest";

import { MODEL_FILES, MODEL_REVISION, verifiedDownload } from "./browserModel";

// Integrity checks of the model download. The real model is exercised by the browser suite
// (playwright.browser.config.ts); nothing here substitutes for it.
const reply = (bytes: Uint8Array) => new Response(new Uint8Array(bytes), { status: 200 });
const config = MODEL_FILES["config.json"];

describe("verified model download", () => {
  it("refuses a file that is not pinned without making a request", async () => {
    const fetcher = vi.fn<typeof fetch>();
    await expect(verifiedDownload("onnx/model.onnx", fetcher, () => undefined)).rejects.toThrow(/unpinned/);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("requests only the pinned revision, without credentials", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(reply(new Uint8Array(config?.size ?? 0)));
    await expect(verifiedDownload("config.json", fetcher, () => undefined)).rejects.toThrow(/integrity/);
    const [url, init] = fetcher.mock.calls[0] ?? [];
    expect(url).toBe(`https://huggingface.co/Horizon-Labs/phishing-scam-detector-base/resolve/${MODEL_REVISION}/config.json`);
    expect(init?.credentials).toBe("omit");
  });

  it.each([
    ["shorter", 10, /incomplete/],
    ["longer", (config?.size ?? 0) + 1, /larger than the pinned size/],
  ])("refuses a %s file", async (_, size, message) => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(reply(new Uint8Array(size)));
    await expect(verifiedDownload("config.json", fetcher, () => undefined)).rejects.toThrow(message);
  });

  it("refuses an HTTP failure", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(null, { status: 503 }));
    await expect(verifiedDownload("config.json", fetcher, () => undefined)).rejects.toThrow(/download failed/);
  });

  it("pins exactly the files the upstream SHA256SUMS lists for this revision", () => {
    expect(Object.keys(MODEL_FILES).sort()).toEqual([
      "config.json", "onnx/model_quantized.onnx", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json",
    ]);
    for (const file of Object.values(MODEL_FILES)) expect(file.sha256).toMatch(/^[0-9a-f]{64}$/);
  });
});
