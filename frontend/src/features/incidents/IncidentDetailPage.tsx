// Incident detail (DESIGN.md "Incident detail"): events first, then the assessment. Unknown
// tier and null scores are shown as such; native model output is labelled uncalibrated; no
// message text exists to show. Reviews are postponed beyond MVP-1, so no review UI appears.
import { useCallback } from "react";
import { Link, useLocation, useParams } from "react-router";

import { useApi } from "../../app/ApiContext";
import { ADMIN_INCIDENTS, adminIncident } from "../../app/routes";
import { RiskBadge, StatusBadge } from "../../components/Badges";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { CopyableId } from "../../components/CopyableId";
import { StageList } from "../../components/StageList";
import { LOADING, StateView, describeError } from "../../components/StateView";
import { Timestamp } from "../../components/Timestamp";
import { getIncident } from "../../lib/api/endpoints";
import { isApiError } from "../../lib/api/errors";
import type { Assessment, IncidentDetail, IncidentEvent } from "../../lib/api/types";
import {
  CHANNEL_LABELS,
  KIND_LABELS,
  NOT_AVAILABLE,
  formatClockTime,
  formatScore,
  reasonCodeLabel,
  shortId,
} from "../../lib/format";
import { useResource } from "../../lib/useResource";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function backTarget(state: unknown): string {
  const from = (state as { from?: unknown } | null)?.from;
  return typeof from === "string" && from.startsWith(ADMIN_INCIDENTS) ? from : ADMIN_INCIDENTS;
}

function Versions({ versions }: { versions: Record<string, string> }) {
  const entries = Object.entries(versions);
  if (entries.length === 0) return <>{NOT_AVAILABLE}</>;
  return (
    <>
      {entries.map(([stage, version]) => (
        <span key={stage} className="copyable-id">
          {stage}: {version}{" "}
        </span>
      ))}
    </>
  );
}

function EventCard({ event, index }: { event: IncidentEvent; index: number }) {
  return (
    <li className="card event">
      <h3>
        Event {index + 1}: {CHANNEL_LABELS[event.channel]}
      </h3>
      <dl className="facts">
        <dt>Event time</dt>
        <dd>
          <Timestamp iso={event.occurred_at} />
        </dd>
        <dt>Received</dt>
        <dd>
          <Timestamp iso={event.received_at} />
        </dd>
        <dt>Analysis</dt>
        <dd>
          <StatusBadge status={event.analysis_status} />
        </dd>
        <dt>Processing time</dt>
        <dd>{event.processing_ms} ms</dd>
        {event.channel === "sms" ? (
          <>
            <dt>SMS score</dt>
            <dd>{formatScore(event.sms_score)} (no calibrated score exists)</dd>
          </>
        ) : null}
        <dt>Reason codes</dt>
        <dd>
          {event.reason_codes.length === 0
            ? "None"
            : event.reason_codes.map((code) => (
                <span key={code} className="reason-code">
                  {reasonCodeLabel(code)} <span className="shell-meta">({code})</span>
                </span>
              ))}
        </dd>
      </dl>
      <h4 className="visually-hidden">Analysis stages</h4>
      <StageList stages={event.stages} modelVersions={event.model_versions} />
    </li>
  );
}

function AssessmentSection({ assessment }: { assessment: Assessment }) {
  return (
    <section className="card" aria-labelledby="assessment-heading">
      <p className="eyebrow">Current assessment</p>
      <h2 id="assessment-heading">Assessment (revision {assessment.revision})</h2>
      <p>
        <RiskBadge tier={assessment.tier} />
      </p>
      {assessment.tier === "unknown" ? (
        <p>
          The tier stays unknown and the scores stay empty because no calibrated signal exists.
          This is not a judgement that the message is safe.
        </p>
      ) : null}
      <dl className="facts">
        <dt>Base score</dt>
        <dd>{formatScore(assessment.base_score)}</dd>
        <dt>Fusion score</dt>
        <dd>{formatScore(assessment.fusion_score)}</dd>
        <dt>Policy risk score</dt>
        <dd>{formatScore(assessment.final_score)}</dd>
        <dt>Analysis</dt>
        <dd>
          <StatusBadge status={assessment.analysis_status} />
        </dd>
        <dt>Policy version</dt>
        <dd className="copyable-id">{assessment.policy_version}</dd>
        <dt>Model versions</dt>
        <dd>
          <Versions versions={assessment.model_versions} />
        </dd>
        <dt>Assessed</dt>
        <dd>
          <Timestamp iso={assessment.created_at} />
        </dd>
      </dl>
    </section>
  );
}

function Detail({ incident }: { incident: IncidentDetail }) {
  return (
    <>
      <div className="incident-header">
        <p className="eyebrow">Incident record</p>
        <h1>Incident {shortId(incident.id)}</h1>
        <p className="incident-id">
          <CopyableId label="Incident ID" value={incident.id} />
        </p>
        <p className="badge-row">
          <span className="badge">{KIND_LABELS[incident.kind]}</span>
          <RiskBadge tier={incident.tier} />
          <StatusBadge status={incident.analysis_status} />
          <span className="badge">Assessment revision {incident.current_revision}</span>
        </p>
      </div>
      <Banner>
        Message text is not retained. KAVACH keeps only analysis evidence, and it expires after 7
        days.
      </Banner>
      <div className="detail-layout">
        <section aria-labelledby="events-heading" className="detail-evidence">
          <p className="eyebrow">Event timeline</p>
          <h2 id="events-heading">Evidence</h2>
          <ol className="event-list">
            {incident.events.map((event, index) => (
              <EventCard key={event.id} event={event} index={index} />
            ))}
          </ol>
        </section>
        <div className="detail-side">
          <AssessmentSection assessment={incident.assessment} />
          <section className="card" aria-labelledby="related-heading">
            <h2 id="related-heading">Related incidents</h2>
            {incident.related_incident_ids.length === 0 ? (
              <p>None. Cross-channel correlation is not part of this release.</p>
            ) : (
              <ul className="related-list">
                {incident.related_incident_ids.map((id) => (
                  <li key={id}>
                    <Link to={adminIncident(id)}>
                      Incident <span className="copyable-id">{shortId(id)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

const NOT_FOUND = {
  kind: "notFound" as const,
  title: "Incident unavailable or expired",
  message: "It does not exist, or its evidence has passed the 7-day retention.",
};

export function IncidentDetailPage() {
  const { incidentId = "" } = useParams();
  const location = useLocation();
  const client = useApi();
  const back = backTarget(location.state);
  const valid = UUID.test(incidentId);
  const loader = useCallback(
    (signal: AbortSignal) =>
      valid
        ? getIncident(client, incidentId, signal).then((response) => response.data)
        : Promise.resolve(null),
    [client, incidentId, valid],
  );
  const resource = useResource(incidentId, loader);
  const backLink = <Link to={back}>Back to incident history</Link>;

  let content;
  if (!valid) {
    // A malformed ID is never sent to the server; it is the same "unavailable" answer.
    content = <StateView state={NOT_FOUND} action={backLink} />;
  } else if (resource.data === null) {
    if (resource.loading) {
      content = <StateView state={LOADING} />;
    } else if (isApiError(resource.error) && resource.error.status === 404) {
      content = <StateView state={NOT_FOUND} action={backLink} />;
    } else {
      content = (
        <StateView
          state={describeError(resource.error)}
          action={<Button onClick={resource.reload}>Try again</Button>}
        />
      );
    }
  } else {
    content = (
      <>
        {resource.stale ? (
          <Banner tone="error">
            Couldn&apos;t refresh. Showing the incident as of{" "}
            {resource.updatedAt !== null ? formatClockTime(resource.updatedAt) : "earlier"}.
          </Banner>
        ) : null}
        <Detail incident={resource.data} />
      </>
    );
  }

  return (
    <>
      <nav aria-label="Breadcrumb" className="breadcrumb">
        {backLink}
        {valid && resource.data !== null ? (
          <Button variant="secondary" pending={resource.loading} pendingLabel="Refreshing…" onClick={resource.reload}>
            Refresh
          </Button>
        ) : null}
      </nav>
      {content}
    </>
  );
}
