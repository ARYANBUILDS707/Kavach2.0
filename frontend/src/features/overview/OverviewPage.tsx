// Overview: model readiness (shared status, no extra request), the most recent SMS incidents and
// summary counts computed only from that one page of real records, labelled as such. There is
// no counts endpoint, so nothing here claims totals.
import { useCallback } from "react";
import { Link } from "react-router";

import { useApi } from "../../app/ApiContext";
import { useModelStatus } from "../../app/ModelStatusProvider";
import { ModelStateBadge } from "../../components/Badges";
import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { LOADING, StateView, describeError } from "../../components/StateView";
import { listIncidents } from "../../lib/api/endpoints";
import type { IncidentSummary } from "../../lib/api/types";
import { formatClockTime } from "../../lib/format";
import { useResource } from "../../lib/useResource";
import { IncidentTable } from "../incidents/IncidentTable";

export const SUMMARY_WINDOW = 25;
export const RECENT_ROWS = 10;

function ModelCard() {
  const { status, error, loading, refresh } = useModelStatus();
  return (
    <section className="card" aria-labelledby="overview-model-heading">
      <h2 id="overview-model-heading">SMS model readiness</h2>
      {status !== null ? (
        <>
          <p>
            <ModelStateBadge state={status.state} />
          </p>
          <p>
            Readiness is operational only. Outputs are uncalibrated and the model is not validated
            on KAVACH data.
          </p>
          <Link to="/system">System status</Link>
        </>
      ) : loading ? (
        <StateView state={LOADING} />
      ) : (
        <StateView state={describeError(error)} action={<Button onClick={refresh}>Check again</Button>} />
      )}
    </section>
  );
}

function SummaryCards({ items, hasMore }: { items: IncidentSummary[]; hasMore: boolean }) {
  const count = (status: IncidentSummary["analysis_status"]) =>
    items.filter((item) => item.analysis_status === status).length;
  const unknownTier = items.filter((item) => item.tier === "unknown").length;
  const scope = hasMore
    ? `Counted over the ${String(items.length)} most recent SMS incident records (more exist).`
    : `Counted over all ${String(items.length)} SMS incident records currently retained.`;
  return (
    <section aria-labelledby="summary-heading">
      <h2 id="summary-heading">Recent SMS records at a glance</h2>
      <p className="shell-meta">{scope} These are record counts, not unique attacks.</p>
      <ul className="summary-cards">
        <li className="card summary">
          <span className="summary-value">{items.length}</span>
          <span>records in this window</span>
        </li>
        <li className="card summary">
          <span className="summary-value">{count("complete")}</span>
          <span>with completed model analysis</span>
        </li>
        <li className="card summary">
          <span className="summary-value">{count("partial")}</span>
          <span>with partial analysis</span>
        </li>
        <li className="card summary">
          <span className="summary-value">{count("unavailable")}</span>
          <span>with analysis unavailable</span>
        </li>
        <li className="card summary">
          <span className="summary-value">{unknownTier}</span>
          <span>with risk tier unknown (no calibrated signal)</span>
        </li>
      </ul>
    </section>
  );
}

export function OverviewPage() {
  const client = useApi();
  // One request serves both the summary and the recent list.
  const loader = useCallback(
    (signal: AbortSignal) =>
      listIncidents(client, { channel: "sms", limit: SUMMARY_WINDOW }, signal),
    [client],
  );
  const recent = useResource("overview", loader);
  const items = recent.data?.data ?? [];

  let incidents;
  if (recent.data === null) {
    incidents = recent.loading ? (
      <StateView state={LOADING} />
    ) : (
      <StateView
        state={describeError(recent.error)}
        action={<Button onClick={recent.reload}>Try again</Button>}
      />
    );
  } else if (items.length === 0) {
    incidents = (
      <StateView
        state={{
          kind: "empty",
          title: "No SMS incidents in the last 7 days",
          message: "Evidence expires after 7 days, and nothing newer has arrived.",
        }}
      />
    );
  } else {
    incidents = (
      <>
        <SummaryCards items={items} hasMore={recent.data.page.has_more} />
        <section aria-labelledby="recent-heading">
          <h2 id="recent-heading">Most recent SMS incidents</h2>
          <IncidentTable
            items={items.slice(0, RECENT_ROWS)}
            caption="Most recent SMS incidents"
            returnTo="/incidents"
          />
          <Link to="/incidents">View the full incident history</Link>
        </section>
      </>
    );
  }

  return (
    <>
      <div className="page-header">
        <h1>Overview</h1>
        <div className="page-actions">
          <span className="shell-meta">
            {recent.updatedAt !== null ? `Last updated ${formatClockTime(recent.updatedAt)}` : null}
          </span>
          <Button variant="secondary" pending={recent.loading} pendingLabel="Refreshing…" onClick={recent.reload}>
            Refresh
          </Button>
        </div>
      </div>
      <ModelCard />
      {recent.stale ? (
        <Banner tone="error">
          Couldn&apos;t refresh. Showing records from{" "}
          {recent.updatedAt !== null ? formatClockTime(recent.updatedAt) : "earlier"}.
        </Banner>
      ) : null}
      {incidents}
    </>
  );
}
