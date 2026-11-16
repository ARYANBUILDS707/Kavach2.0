import { useRef, useState, type SubmitEvent } from "react";

import { Button } from "../../components/Button";
import { SiteFooter } from "../../components/SiteFooter";
import { SiteHeader } from "../../components/SiteHeader";
import { classify, DOWNLOAD_BYTES, loadModel, MODEL_VERSION, type BrowserPrediction } from "./browserModel";

const MAX_CHARS = 500;
const megabytes = (bytes: number) => `${String(Math.round(bytes / 1e6))} MB`;
const MODEL_SIZE = megabytes(DOWNLOAD_BYTES);

// Shortcuts only fill the text box with invented messages; the prediction always comes from the model.
const SAMPLES = [
  { id: "fraud", label: "Try Fraud Example",
    text: "Your Northpay account is frozen. Confirm your PIN at the link now to avoid closure." },
  { id: "spam", label: "Try Spam Example",
    text: "Mega Sale at ShopFictional! Flat 50% off this weekend, reply STOP to opt out." },
  { id: "legitimate", label: "Try Legitimate Example",
    text: "Running ten minutes late for dinner, order without me." },
] as const;

// What each class means, as the model's authors define its labels. Not an explanation of a result.
const OUTCOMES = {
  fraud: { title: "Fraud", meaning: "The model predicts a scam or phishing attempt, for example a request for money, a PIN, an OTP or a click on a link." },
  spam: { title: "Spam", meaning: "The model predicts unwanted marketing or bulk messaging rather than a scam." },
  legitimate: { title: "Legitimate", meaning: "The model predicts an ordinary message. This never guarantees the message is safe." },
} as const;

type Loaded = Awaited<ReturnType<typeof loadModel>>;
type ModelState =
  | { kind: "idle" }
  | { kind: "downloading"; loaded: number }
  | { kind: "ready"; loaded: Loaded }
  | { kind: "failed"; message: string };

/** Static-build analyzer: the pinned model runs on the visitor's device and no API exists. */
export function BrowserAnalyzerPage() {
  const [model, setModel] = useState<ModelState>({ kind: "idle" });
  const [text, setText] = useState("");
  const [result, setResult] = useState<BrowserPrediction | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Explicit, per-page-visit acknowledgement; never stored.
  const [consent, setConsent] = useState(false);
  const percent = useRef(-1);
  const input = useRef<HTMLTextAreaElement>(null);
  const length = Array.from(text).length;
  const busy = analyzing || model.kind === "downloading";
  const canSubmit = consent && !busy && text.trim() !== "" && length <= MAX_CHARS;

  async function ensureModel(): Promise<Loaded> {
    if (model.kind === "ready") return model.loaded;
    setModel({ kind: "downloading", loaded: 0 });
    try {
      const loaded = await loadModel((bytes) => {
        const next = Math.floor((100 * bytes) / DOWNLOAD_BYTES);
        if (next !== percent.current) { percent.current = next; setModel({ kind: "downloading", loaded: bytes }); }
      });
      setModel({ kind: "ready", loaded });
      return loaded;
    } catch (failure) {
      percent.current = -1;
      const message = failure instanceof Error ? failure.message : "The AI model could not be loaded in this browser.";
      setModel({ kind: "failed", message });
      throw failure;
    }
  }
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    setError(null); setResult(null);
    let loaded: Loaded;
    try { loaded = await ensureModel(); } catch { return; }
    setAnalyzing(true);
    try {
      setResult(await classify(loaded, text));
    } catch {
      setError("The model failed on this message. No prediction was produced.");
    } finally {
      setAnalyzing(false);
    }
  }
  function another() {
    setText(""); setResult(null); setError(null);
    input.current?.focus();
  }

  const outcome = result ? OUTCOMES[result.prediction] : null;
  return <>
    <SiteHeader current="analyze" />
    <main id="main" className="public-analyzer checker">
      <header className="checker-intro">
        <p className="eyebrow">Experimental AI · runs on your device</p>
        <h1>Is this SMS a scam?</h1>
        <p>Paste a message and an AI model predicts whether it is fraud, spam or legitimate. The check
          runs in your browser: your message is not sent anywhere.</p>
      </header>

      <form onSubmit={(event) => { void submit(event); }} className="card analyze-form checker-card" aria-describedby="checker-note">
        <div className="field">
          <label htmlFor="public-sms" className="checker-label">SMS to analyze</label>
          <textarea id="public-sms" ref={input} rows={6} value={text} autoComplete="off" spellCheck={false}
            placeholder="Paste the SMS here. Remove OTPs, passwords and PINs first."
            aria-describedby="sms-limit" disabled={busy}
            onChange={(event) => { setText(event.target.value); setResult(null); setError(null); }} />
          <div className="checker-meta">
            <span id="sms-limit">{length} / {MAX_CHARS} characters</span>
          </div>
        </div>
        <div className="checker-samples" role="group" aria-label="Example messages">
          {SAMPLES.map((sample) => (
            <Button key={sample.id} variant="secondary" className="button-sm" disabled={busy}
              onClick={() => { setText(sample.text); setResult(null); setError(null); }}>{sample.label}</Button>
          ))}
        </div>
        <label className="consent">
          <input type="checkbox" checked={consent} disabled={busy}
            onChange={(event) => { setConsent(event.target.checked); }} />
          <span>I understand the result is an experimental, unvalidated prediction that can be wrong,
            that “Legitimate” does not mean safe, and that I have removed any OTPs, passwords or PINs.</span>
        </label>

        {model.kind === "downloading" ? <div className="checker-progress" role="status">
          <div className="checker-progress-head">
            <span>{model.loaded >= DOWNLOAD_BYTES ? "Starting the AI model…" : "Downloading the AI model…"}</span>
            <span>{megabytes(model.loaded)} of {MODEL_SIZE}</span>
          </div>
          <progress aria-label="AI model download" max={DOWNLOAD_BYTES} value={model.loaded} />
          <p>One-time download, checked against its pinned SHA-256. Keep this tab open.</p>
        </div> : null}
        {analyzing ? <p role="status" className="checker-status">Analyzing on your device…</p> : null}

        <div className="checker-actions">
          <Button type="submit" className="checker-submit" disabled={!canSubmit}
            pending={busy} pendingLabel={model.kind === "downloading" ? "Loading AI model…" : "Analyzing…"}>
            {model.kind === "failed" ? "Retry download and analyze" : "Analyze SMS"}
          </Button>
          <p id="checker-note" className="checker-note">
            {model.kind === "ready" ? "AI model loaded on this device." :
              `First use downloads the AI model once (${MODEL_SIZE}). Analysis starts when it has loaded.`}
          </p>
        </div>
        {model.kind === "failed" ? <p role="alert" className="checker-error">{model.message} No prediction was produced.</p> : null}
        {error ? <p role="alert" className="checker-error">{error}</p> : null}
      </form>

      <div aria-live="polite" aria-atomic="true">
        {result && outcome ? <section className={`card verdict verdict-${result.prediction}`} aria-labelledby="prediction-title">
          <p className="verdict-tag">AI prediction · experimental · unvalidated</p>
          <h2 id="prediction-title"><span className="verdict-dot" aria-hidden="true" />Prediction: {outcome.title}</h2>
          <p className="verdict-meaning">{outcome.meaning}</p>
          {result.truncated ? <p>The message was too long; the model only read the first part.</p> : null}
          <p className="verdict-warning">This prediction can be wrong in either direction and is not a safety verdict.
            “Legitimate” never guarantees a message is safe. If a message worries you, contact the sender
            through a channel you already trust.</p>
          <div className="verdict-foot">
            <Button variant="secondary" onClick={another}>Analyze another SMS</Button>
            <span>Model time: {result.model_ms} ms</span>
          </div>
        </section> : null}
      </div>

      <details className="card checker-details">
        <summary>How it works, privacy &amp; limitations</summary>
        <h2>How it works</h2>
        <p>The pretrained model {MODEL_VERSION} (Horizon-Labs phishing-scam-detector-base, Apache-2.0)
          is downloaded once from its authors' pinned Hugging Face revision ({MODEL_SIZE}). Every file is
          checked against its published SHA-256 before use, then the model runs in this tab with WebAssembly.
          The page shows the predicted class only; the model's scores are not calibrated probabilities.</p>
        <h2>Privacy</h2>
        <p>Your message is analyzed in this tab and is not sent to KAVACH or anyone else, stored or logged.
          Links in a message are never opened. GitHub Pages (this site) and Hugging Face (the model files)
          see your IP address, never your message. Your browser may cache the model files for next time.
          Even so, remove one-time passwords, passwords, PINs, card numbers and other secrets before pasting.</p>
        <h2>Limitations</h2>
        <p>The model is not validated on KAVACH data and its real-world accuracy is unknown. A scam can be
          predicted “Legitimate” and a genuine message “Fraud”. Nothing is blocked or reported for you.
          Long messages are truncated. Phones may not have enough memory for the model; the page then shows
          an error instead of a prediction.</p>
      </details>
    </main>
    <SiteFooter />
  </>;
}
