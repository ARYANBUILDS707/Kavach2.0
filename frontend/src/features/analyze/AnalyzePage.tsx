// Admin SMS analysis (MVP-F3): submit one synthetic SMS through the admin browser path and show
// the receipt and the stored evidence. The text lives only in this component's state: never in
// storage, the URL, logs or any shared client state, and it is cleared after a receipt.
import { useCallback, useId, useRef, useState, type SyntheticEvent } from "react";
import { Link } from "react-router";

import { useApi } from "../../app/ApiContext";
import { useModelStatus } from "../../app/ModelStatusProvider";
import { useSession } from "../../app/SessionProvider";
import { StatusBadge } from "../../components/Badges";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { CopyableId } from "../../components/CopyableId";
import { PageHeader } from "../../components/PageHeader";
import { StageList } from "../../components/StageList";
import { LOADING, StateView, describeError } from "../../components/StateView";
import { Timestamp } from "../../components/Timestamp";
import { getIncident, submitSms } from "../../lib/api/endpoints";
import type { AdminEventReceipt, ModelState, SmsSubmission } from "../../lib/api/types";
import { shortId } from "../../lib/format";
import { useResource } from "../../lib/useResource";
import {
  MAX_TEXT_CHARACTERS,
  characterCount,
  classifyFailure,
  newSubmission,
  validateText,
  warningLabel,
  type Failure,
} from "./submission";

const MODEL_NOTICES: Record<ModelState, string> = {
  disabled:
    "The SMS model is disabled on this deployment. Your message will be stored with the analysis unavailable; no prediction is made.",
  starting: "The SMS model is starting. Submissions are refused until it is ready.",
  unavailable:
    "The SMS model is unavailable. Your message will be stored with the analysis unavailable and a reason.",
  ready:
    "The SMS model is ready. Its native outputs will be shown as stored evidence, labelled uncalibrated.",
};

function ModelNotice() {
  const { status } = useModelStatus();
  if (status === null) return null;
  // A standing notice, not an event: announced politely (status), never as an alert.
  return <Banner>{MODEL_NOTICES[status.state]}</Banner>;
}

/** The stored evidence of the new incident, read back from the server (never inferred). */
function StoredEvidence({ incidentId }: { incidentId: string }) {
  const client = useApi();
  const loader = useCallback(
    (signal: AbortSignal) => getIncident(client, incidentId, signal).then((r) => r.data),
    [client, incidentId],
  );
  const incident = useResource(incidentId, loader);
  if (incident.data === null) {
    return incident.loading ? (
      <StateView state={LOADING} />
    ) : (
      <StateView
        state={describeError(incident.error)}
        action={<Button onClick={incident.reload}>Try again</Button>}
      />
    );
  }
  return (
    <section aria-labelledby="stored-evidence-heading">
      <h3 id="stored-evidence-heading">Stored analysis</h3>
      {incident.data.events.map((event) => (
        <StageList key={event.id} stages={event.stages} modelVersions={event.model_versions} />
      ))}
    </section>
  );
}

function ReceiptPanel({ receipt }: { receipt: AdminEventReceipt }) {
  const [first] = receipt.incident_ids;
  return (
    <section className="card receipt" aria-labelledby="receipt-heading" role="status">
      <h2 id="receipt-heading">
        {receipt.replayed ? "Already stored: showing the original receipt" : "Message stored"}
      </h2>
      <p>The message text was not kept. Only the analysis evidence below is stored.</p>
      <dl className="facts">
        <dt>Analysis</dt>
        <dd>
          <StatusBadge status={receipt.analysis_status} />
        </dd>
        <dt>Notes</dt>
        <dd>
          {receipt.warnings.length === 0
            ? "None"
            : receipt.warnings.map((code) => (
                <span key={code} className="reason-code">
                  {warningLabel(code)}
                </span>
              ))}
        </dd>
        <dt>Received</dt>
        <dd>
          <Timestamp iso={receipt.received_at} />
        </dd>
        <dt>Processing time</dt>
        <dd>{receipt.processing_ms} ms</dd>
        <dt>Event ID</dt>
        <dd>
          <CopyableId value={receipt.external_event_id} />
        </dd>
        <dt>Incidents</dt>
        <dd>
          {receipt.incident_ids.length === 0 ? (
            "None"
          ) : (
            <ul>
              {receipt.incident_ids.map((id) => (
                <li key={id}>
                  <Link to={`/incidents/${id}`}>
                    Open incident <span className="copyable-id">{shortId(id)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </dd>
      </dl>
      {first !== undefined ? <StoredEvidence incidentId={first} /> : null}
    </section>
  );
}

export function AnalyzePage() {
  const client = useApi();
  const { state } = useSession();
  const textId = useId();
  const [text, setText] = useState("");
  const [validation, setValidation] = useState<string | null>(null);
  const [submission, setSubmission] = useState<SmsSubmission | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [failed, setFailed] = useState<Failure | null>(null);
  const [receipt, setReceipt] = useState<AdminEventReceipt | null>(null);
  // A synchronous guard: two clicks in one frame cannot both start a request.
  const inFlight = useRef(false);
  const uncertain = failed?.kind === "uncertain";
  const csrfToken = state.status === "signedIn" ? state.session.csrf_token : null;

  async function send() {
    if (inFlight.current || csrfToken === null) return;
    // After an uncertain outcome only the identical submission may be sent again.
    let body = submission;
    if (!uncertain) {
      const problem = validateText(text);
      setValidation(problem);
      if (problem !== null) return;
      if (body === null || body.text !== text) body = newSubmission(text);
    }
    if (body === null) return;
    inFlight.current = true;
    setSubmission(body);
    setSubmitting(true);
    setFailed(null);
    try {
      const response = await submitSms(client, body, csrfToken);
      setReceipt(response.data);
      setText("");
      setSubmission(null);
    } catch (error) {
      const outcome = classifyFailure(error);
      setFailed(outcome);
      if (outcome.kind === "conflict") setSubmission(null);
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  function startOver() {
    setSubmission(null);
    setFailed(null);
  }

  function onSubmit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    void send();
  }

  const count = characterCount(text);
  const hintId = `${textId}-hint`;
  const errorId = `${textId}-error`;

  return (
    <>
      <PageHeader
        eyebrow="Admin workspace"
        title="Analyze a synthetic SMS"
        lead="Admin only. Submit a fictional message to see how KAVACH stores and analyses it. Do not paste real messages, phone numbers or personal data. The text is sent once and is not kept."
      />
      <ModelNotice />
      <div className="analyze-layout">
        <form className="card analyze-form" onSubmit={onSubmit} aria-label="Submit a synthetic SMS">
          <div className="field">
            <label htmlFor={textId}>Synthetic message text</label>
            <span id={hintId} className="field-hint">
              1 to {MAX_TEXT_CHARACTERS.toLocaleString("en")} characters. {count.toLocaleString("en")}{" "}
              used.
            </span>
            <textarea
              id={textId}
              name="sms-text"
              rows={6}
              value={text}
              readOnly={uncertain || submitting}
              aria-readonly={uncertain || submitting || undefined}
              aria-invalid={validation !== null || undefined}
              aria-describedby={validation !== null ? `${hintId} ${errorId}` : hintId}
              autoComplete="off"
              spellCheck={false}
              onChange={(event) => {
                setText(event.target.value);
                if (validation !== null) setValidation(validateText(event.target.value));
              }}
            />
            {validation !== null ? (
              <span id={errorId} className="field-error" role="alert">
                {validation}
              </span>
            ) : null}
          </div>
          {failed !== null ? (
            <div className="banner banner-error" role="alert">
              <h2>{failed.title}</h2>
              <p>{failed.message}</p>
              {failed.requestId !== null ? (
                <CopyableId label="Request ID" value={failed.requestId} />
              ) : null}
              {uncertain ? (
                <p className="filter-actions">
                  <Button variant="secondary" onClick={startOver}>
                    Discard and start a new submission
                  </Button>
                </p>
              ) : null}
            </div>
          ) : null}
          <div className="analyze-actions">
            <Button type="submit" pending={submitting} pendingLabel="Submitting…">
              {uncertain ? "Retry the same submission" : "Submit"}
            </Button>
          </div>
        </form>
      <HandlingPanel />
      </div>
      {receipt !== null ? <ReceiptPanel receipt={receipt} /> : null}
    </>
  );
}

/** What every submission carries, stated rather than editable: the server fixes the source and
 * the browser creates the identifiers, so none of these are inputs. */
function HandlingPanel() {
  return (
    <section className="card handling-card" aria-labelledby="handling-heading">
      <p className="eyebrow">Submission details</p>
      <h2 id="handling-heading">How this submission is handled</h2>
      <dl className="facts">
        <dt>Source</dt>
        <dd>Simulator, fixed for browser submissions</dd>
        <dt>Event identifier</dt>
        <dd>
          Created in your browser when you submit: <span className="copyable-id">ui-</span> and a
          random UUID
        </dd>
        <dt>Subscriber token</dt>
        <dd>
          Synthetic and new for each submission: <span className="copyable-id">ui-sub-</span> and a
          random UUID
        </dd>
        <dt>Event time</dt>
        <dd>The moment you submit</dd>
        <dt>Retries</dt>
        <dd>Never automatic. After an unclear outcome you choose to resend the same submission.</dd>
      </dl>
    </section>
  );
}
