import { useRef, useState, type SubmitEvent } from "react";

import { Button } from "../../components/Button";
import { SiteFooter } from "../../components/SiteFooter";
import { SiteHeader } from "../../components/SiteHeader";
import { classify, DOWNLOAD_BYTES, loadModel, MODEL_VERSION, type BrowserPrediction } from "./browserModel";

const labels = { fraud: "Fraud", spam: "Spam", legitimate: "Legitimate" };
const MAX_CHARS = 500;
const megabytes = (bytes: number) => `${String(Math.round(bytes / 1e6))} MB`;
type ModelState =
  | { kind: "idle" }
  | { kind: "loading"; loaded: number }
  | { kind: "ready"; loaded: Awaited<ReturnType<typeof loadModel>> }
  | { kind: "failed"; message: string };

/** Static-build analyzer: the pinned model runs on the visitor's device and no API exists. */
export function BrowserAnalyzerPage() {
  const [model, setModel] = useState<ModelState>({ kind: "idle" });
  const [text, setText] = useState("");
  const [result, setResult] = useState<BrowserPrediction | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const progress = useRef(0);
  const length = Array.from(text).length;
  const ready = model.kind === "ready";

  function load() {
    setModel({ kind: "loading", loaded: 0 });
    loadModel((loaded) => {
      // Re-render at most once per whole percent.
      const percent = Math.floor((100 * loaded) / DOWNLOAD_BYTES);
      if (percent !== progress.current) { progress.current = percent; setModel({ kind: "loading", loaded }); }
    }).then((loaded) => { setModel({ kind: "ready", loaded }); }, (failure: unknown) => {
      progress.current = 0;
      setModel({ kind: "failed", message: failure instanceof Error ? failure.message
        : "The model could not be loaded in this browser." });
    });
  }
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (model.kind !== "ready" || pending || !text.trim() || length > MAX_CHARS) return;
    setPending(true); setError(null); setResult(null);
    try {
      setResult(await classify(model.loaded, text));
      setText("");
    } catch {
      setError("The model failed on this message. No prediction was produced.");
    } finally {
      setPending(false);
    }
  }
  return <>
    <SiteHeader current="analyze" />
    <main id="main" className="public-analyzer">
      <p className="eyebrow">Experimental · unvalidated · fictional messages only</p>
      <h1>Analyze an SMS</h1>
      <p>No login or signup. The actual pretrained SMS model runs inside your browser.</p>
      <div className="card">
        <h2>Before you try</h2>
        <p>The model is not validated on KAVACH data. A prediction can be wrong in either direction;
          “Legitimate” does not mean safe. No calibrated fraud probability is available, and nothing
          is blocked or reported for you.</p>
        <p>Your message stays on this device: it is analyzed in this tab and is not sent to KAVACH or
          anyone else, stored or logged. Links in a message are never opened. Use fictional text anyway;
          do not paste passwords or OTPs.</p>
        <p>First use downloads the model ({megabytes(DOWNLOAD_BYTES)}) from Hugging Face, which sees
          your IP address. Every file is checked against its pinned SHA-256 before use. Phones may
          not have enough memory.</p>
      </div>
      {model.kind === "idle" || model.kind === "failed" ? <div className="card">
        {model.kind === "failed" ? <p role="alert">{model.message}</p> : null}
        <Button onClick={load}>{model.kind === "failed" ? "Retry model download" : `Load model (${megabytes(DOWNLOAD_BYTES)})`}</Button>
      </div> : null}
      {model.kind === "loading" ? <div className="card" role="status">
        <label htmlFor="model-progress">Downloading and verifying the model…</label>
        <progress id="model-progress" max={DOWNLOAD_BYTES} value={model.loaded} />
        <p>{megabytes(model.loaded)} of {megabytes(DOWNLOAD_BYTES)}</p>
      </div> : null}
      {ready ? <p role="status">Model ready on this device: {MODEL_VERSION}.</p> : null}
      <form onSubmit={(event) => { void submit(event); }} className="card analyze-form analyzer-form">
        <div className="field">
          <label htmlFor="public-sms">Fictional SMS</label>
          <p id="sms-limit" className="field-hint">{MAX_CHARS} characters maximum.
            Long messages may also be truncated by the model.</p>
          <textarea id="public-sms" rows={7} value={text} autoComplete="off" spellCheck={false}
            aria-describedby="sms-limit" disabled={!ready || pending}
            onChange={(event) => { setText(event.target.value); setResult(null); setError(null); }} />
          <span>{length} / {MAX_CHARS}</span>
        </div>
        <div className="cta-row">
          <Button type="submit" pending={pending} pendingLabel="Analyzing…"
            disabled={!ready || !text.trim() || length > MAX_CHARS}>Analyze</Button>
          <Button variant="secondary" disabled={pending} onClick={() => {
            setText(""); setResult(null); setError(null);
          }}>Clear</Button>
        </div>
      </form>
      {error ? <p role="alert">{error}</p> : null}
      <div aria-live="polite" aria-atomic="true">
        {result ? <section className="card" aria-labelledby="prediction-title">
          <p className="eyebrow">Actual model output on this device · experimental</p>
          <h2 id="prediction-title">Prediction: {labels[result.prediction]}</h2>
          <p>This is an unvalidated prediction, not a safety verdict.</p>
          {result.truncated ? <p>The model truncated this message; it did not analyze all of it.</p> : null}
          <p>Model time: {result.model_ms} ms</p>
        </section> : null}
      </div>
    </main>
    <SiteFooter />
  </>;
}
