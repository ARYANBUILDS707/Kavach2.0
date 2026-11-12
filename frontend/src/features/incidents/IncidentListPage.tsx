// SMS incident history (DESIGN.md "Incident feed"): URL-synchronised filters, cursor paging with
// "Load more", and the loading, empty, no-match, stale, error and forbidden states.
import { useState, type SyntheticEvent } from "react";
import { useSearchParams } from "react-router";

import { Banner } from "../../components/Banner";
import { Button } from "../../components/Button";
import { ADMIN_INCIDENTS } from "../../app/routes";
import { PageHeader } from "../../components/PageHeader";
import { LOADING, StateView, describeError } from "../../components/StateView";
import { isApiError } from "../../lib/api/errors";
import { formatClockTime } from "../../lib/format";
import {
  DEFAULT_FILTERS,
  filtersFromParams,
  filtersToParams,
  isFiltered,
  isoToLocalInput,
  localInputToIso,
  rangeError,
  type IncidentFilters,
} from "./filters";
import { IncidentTable } from "./IncidentTable";
import { useIncidentPages } from "./useIncidentPages";

function FilterBar({
  applied,
  onApply,
}: {
  applied: IncidentFilters;
  onApply: (filters: IncidentFilters) => void;
}) {
  const [channel, setChannel] = useState(applied.channel);
  const [kind, setKind] = useState(applied.kind ?? "");
  const [tier, setTier] = useState(applied.tier ?? "");
  const [from, setFrom] = useState(isoToLocalInput(applied.from));
  const [to, setTo] = useState(isoToLocalInput(applied.to));
  const [problem, setProblem] = useState<string | null>(null);

  function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const fromIso = localInputToIso(from);
    const toIso = localInputToIso(to);
    const error = rangeError(fromIso, toIso);
    setProblem(error);
    if (error !== null) return;
    onApply({
      channel,
      kind: kind === "" ? null : (kind as IncidentFilters["kind"]),
      tier: tier === "" ? null : (tier as IncidentFilters["tier"]),
      from: fromIso,
      to: toIso,
    });
  }

  function clear() {
    setChannel("sms");
    setKind("");
    setTier("");
    setFrom("");
    setTo("");
    setProblem(null);
    onApply(DEFAULT_FILTERS);
  }

  return (
    <form className="filter-bar" onSubmit={submit} aria-label="Filter incidents">
      <div className="field">
        <label htmlFor="filter-channel">Channel</label>
        <select
          id="filter-channel"
          value={channel}
          onChange={(event) => {
            setChannel(event.target.value as IncidentFilters["channel"]);
          }}
        >
          <option value="sms">SMS</option>
          <option value="call">Calls</option>
          <option value="all">All channels</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="filter-kind">Kind</label>
        <select
          id="filter-kind"
          value={kind}
          onChange={(event) => {
            setKind(event.target.value);
          }}
        >
          <option value="">Any kind</option>
          <option value="standalone">Standalone</option>
          <option value="pair">Pair</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="filter-tier">Risk tier</label>
        <select
          id="filter-tier"
          value={tier}
          onChange={(event) => {
            setTier(event.target.value);
          }}
        >
          <option value="">Any tier</option>
          <option value="unknown">Unknown</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="filter-from">Event time from</label>
        <input
          id="filter-from"
          type="datetime-local"
          value={from}
          aria-describedby="filter-time-hint"
          aria-invalid={problem !== null || undefined}
          onChange={(event) => {
            setFrom(event.target.value);
          }}
        />
      </div>
      <div className="field">
        <label htmlFor="filter-to">Event time before</label>
        <input
          id="filter-to"
          type="datetime-local"
          value={to}
          aria-describedby="filter-time-hint filter-range-error"
          aria-invalid={problem !== null || undefined}
          onChange={(event) => {
            setTo(event.target.value);
          }}
        />
      </div>
      <p id="filter-time-hint" className="field-hint">
        Times are in your local time zone. The start is inclusive, the end exclusive.
      </p>
      {problem ? (
        <p id="filter-range-error" className="field-error" role="alert">
          {problem}
        </p>
      ) : null}
      <div className="filter-actions">
        <Button type="submit">Apply filters</Button>
        <Button variant="secondary" onClick={clear}>
          Clear filters
        </Button>
      </div>
    </form>
  );
}

export function IncidentListPage() {
  const [params, setParams] = useSearchParams();
  const filters = filtersFromParams(params);
  const pages = useIncidentPages(filters);
  const returnTo = `${ADMIN_INCIDENTS}${params.toString() ? `?${params.toString()}` : ""}`;
  const filtered = isFiltered(filters);

  function apply(next: IncidentFilters) {
    setParams(filtersToParams(next));
  }

  let body;
  if (pages.loading && pages.items.length === 0) {
    body = <StateView state={LOADING} />;
  } else if (pages.error !== null && pages.items.length === 0) {
    body = (
      <StateView
        state={describeError(pages.error)}
        action={<Button onClick={pages.refresh}>Try again</Button>}
      />
    );
  } else if (pages.items.length === 0) {
    body = filtered ? (
      <StateView
        state={{
          kind: "empty",
          title: "No incidents match these filters",
          message: "Change or clear the filters to see more incident records.",
        }}
      />
    ) : (
      <StateView
        state={{
          kind: "empty",
          title: "No SMS incidents in the last 7 days",
          message: "Evidence expires after 7 days, and nothing newer has arrived.",
        }}
      />
    );
  } else {
    body = (
      <>
        <IncidentTable items={pages.items} caption="Incident records" returnTo={returnTo} />
        <div className="list-status">
          <p className="shell-meta" aria-live="polite">
            {pages.items.length} incident record{pages.items.length === 1 ? "" : "s"} loaded
            {pages.hasMore ? "; more are available" : ""}.
          </p>
          {pages.hasMore ? (
            <Button
              variant="secondary"
              pending={pages.loadingMore}
              pendingLabel="Loading more…"
              onClick={pages.loadMore}
            >
              Load more
            </Button>
          ) : null}
        </div>
        {pages.moreError ? (
          <Banner tone="error">
            {isApiError(pages.moreError) && pages.moreError.code === "INVALID_CURSOR"
              ? "The list changed while you were paging. Reload from the start."
              : describeError(pages.moreError).message}{" "}
            <Button variant="secondary" onClick={pages.refresh}>
              Reload from the start
            </Button>
          </Banner>
        ) : null}
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="Investigation"
        title="Incident history"
        lead="Standalone incident records, newest event first. Pair and standalone records can share evidence. Message text is never retained."
        actions={
          <>
            <span className="shell-meta">
              {pages.updatedAt !== null ? `Last updated ${formatClockTime(pages.updatedAt)}` : null}
            </span>
            <Button variant="secondary" pending={pages.loading} pendingLabel="Refreshing…" onClick={pages.refresh}>
              Refresh
            </Button>
          </>
        }
      />
      <section className="card filter-card" aria-labelledby="filter-heading">
        <p className="eyebrow" id="filter-heading">
          Filters
        </p>
        <FilterBar key={params.toString()} applied={filters} onApply={apply} />
      </section>
      {pages.stale ? (
        <Banner tone="error">
          Couldn&apos;t refresh. Showing records from{" "}
          {pages.updatedAt !== null ? formatClockTime(pages.updatedAt) : "earlier"}, which may be
          out of date.
        </Banner>
      ) : null}
      {body}
    </>
  );
}
