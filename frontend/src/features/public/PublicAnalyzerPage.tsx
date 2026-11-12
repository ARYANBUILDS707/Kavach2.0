import { useEffect, useRef, useState, type SubmitEvent } from "react";

import { Button } from "../../components/Button";
import { SiteFooter } from "../../components/SiteFooter";
import { SiteHeader } from "../../components/SiteHeader";
import { AnalyzerLimitError, analyzerRequest, parsePrediction, parseStatus, type AnalyzerStatus, type Prediction } from "./analyzer";

const labels = { fraud: "Fraud", spam: "Spam", legitimate: "Legitimate" };

export function PublicAnalyzerPage() {
  const [status, setStatus] = useState<AnalyzerStatus | null>(null);
  const [text, setText] = useState("");
  const [result, setResult] = useState<Prediction | null>(null);
  const [pending, setPending] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const active = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void analyzerRequest(undefined, controller.signal).then(parseStatus).then(setStatus).catch(() => {
      if (!controller.signal.aborted) setError("Analyzer status unavailable. Reload to retry.");
    });
    return () => { controller.abort(); active.current?.abort(); };
  }, []);
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => { setCooldown(cooldown - 1); }, 1000);
    return () => { window.clearTimeout(timer); };
  }, [cooldown]);
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || cooldown > 0 || !status?.enabled || !text.trim() || Array.from(text).length > status.max_chars) return;
    const controller = new AbortController();
    active.current = controller;
    const timer = window.setTimeout(() => { controller.abort(); }, 40_000);
    setPending(true); setError(null); setResult(null);
    try {
      const prediction = parsePrediction(await analyzerRequest(JSON.stringify({ text }), controller.signal));
      setResult(prediction);
      setText("");
    } catch (failure) {
      if (failure instanceof AnalyzerLimitError) setCooldown(failure.retryAfterSeconds);
      setError(failure instanceof Error && failure.name !== "AbortError" ? failure.message :
        "Analysis timed out. No prediction was returned.");
    } finally {
      window.clearTimeout(timer); active.current = null; setPending(false);
    }
  }
  return <>
    <SiteHeader current="analyze" />
    <main id="main" className="public-analyzer">
      <p className="eyebrow">Experimental · local fictional messages only</p>
      <h1>Analyze an SMS</h1>
      <p>No login or signup. When enabled locally, this runs the actual SMS model.</p>
      <div className="card">
        <h2>Before you try</h2>
        <p>The model is not validated on KAVACH data. A prediction can be wrong in either direction;
          “Legitimate” does not mean safe. No calibrated fraud probability is available.</p>
        <p>Use fictional text only. Do not paste personal information, real messages, passwords or OTPs.
          Text is processed in memory on this server and is not saved as an event or incident.
          No external AI service receives it. Memory erasure is not guaranteed.</p>
      </div>
      {status === null && !error ? <p role="status">Checking analyzer availability…</p> : null}
      {status && !status.enabled ? <p role="status">Public analysis is disabled. Hosted inference awaits
        owner approval and privacy, security and release checks. Recorded examples remain available.</p> : null}
      <form onSubmit={(event) => { void submit(event); }} className="card analyze-form analyzer-form">
        <div className="field">
          <label htmlFor="public-sms">Fictional SMS</label>
          <p id="sms-limit" className="field-hint">{status?.max_chars ?? 500} characters maximum.
            Long messages may also be truncated by the model.</p>
          <textarea id="public-sms" rows={7} value={text} autoComplete="off" spellCheck={false}
            aria-describedby="sms-limit" disabled={!status?.enabled || pending}
            onChange={(event) => { setText(event.target.value); setResult(null); setError(null); }} />
          <span>{Array.from(text).length} / {status?.max_chars ?? 500}</span>
        </div>
        <div className="cta-row">
          <Button type="submit" pending={pending} pendingLabel="Analyzing…"
            disabled={!status?.enabled || cooldown > 0 || !text.trim() || Array.from(text).length > status.max_chars}>Analyze</Button>
          <Button variant="secondary" disabled={pending} onClick={() => {
            setText(""); setResult(null); setError(null);
          }}>Clear</Button>
        </div>
      </form>
      {cooldown > 0 ? <p role="status">Try again in {cooldown} seconds.</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      <div aria-live="polite" aria-atomic="true">
        {result ? <section className="card" aria-labelledby="prediction-title">
          <p className="eyebrow">Actual model output · experimental</p>
          <h2 id="prediction-title">Prediction: {labels[result.prediction]}</h2>
          <p>This is an unvalidated prediction, not a safety verdict.</p>
          {result.truncated ? <p>The model truncated this message; it did not analyze all of it.</p> : null}
          <p>Model time: {result.model_ms} ms · Analysis time: {result.total_ms} ms</p>
        </section> : null}
      </div>
    </main>
    <SiteFooter />
  </>;
}
