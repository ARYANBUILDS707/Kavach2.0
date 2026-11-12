// Cursor pagination over GET /incidents. The first page loads when the filters change (or on
// refresh); "Load more" appends the next page with the server's cursor. Loading and staleness
// are derived from which request settled, so no state is reset synchronously inside an effect.
import { useCallback, useEffect, useRef, useState } from "react";

import { useApi } from "../../app/ApiContext";
import { listIncidents } from "../../lib/api/endpoints";
import { isApiError, type ApiError } from "../../lib/api/errors";
import type { IncidentSummary } from "../../lib/api/types";
import { filtersToQuery, type IncidentFilters } from "./filters";

export interface IncidentPages {
  items: IncidentSummary[];
  hasMore: boolean;
  loading: boolean;
  loadingMore: boolean;
  /** Failure of the first page (nothing to show) or of a refresh (items are stale). */
  error: ApiError | Error | null;
  /** Failure of "Load more"; the loaded items stay valid. */
  moreError: ApiError | Error | null;
  stale: boolean;
  updatedAt: number | null;
  loadMore: () => void;
  refresh: () => void;
}

interface Loaded {
  filterKey: string;
  /** The first-page request (filters + attempt) these items descend from. */
  token: string;
  items: IncidentSummary[];
  cursor: string | null;
  error: ApiError | Error | null;
  moreError: ApiError | Error | null;
  updatedAt: number | null;
}

function asError(failure: unknown): ApiError | Error {
  return isApiError(failure) || failure instanceof Error ? failure : new Error("failed");
}

export function useIncidentPages(
  filters: IncidentFilters,
  now: () => number = Date.now,
): IncidentPages {
  const client = useApi();
  const filterKey = JSON.stringify(filters);
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const moreController = useRef<AbortController | null>(null);
  const token = `${filterKey}#${String(attempt)}`;

  useEffect(() => {
    moreController.current?.abort();
    const controller = new AbortController();
    const current = JSON.parse(filterKey) as IncidentFilters;
    listIncidents(client, filtersToQuery(current), controller.signal).then(
      (response) => {
        if (controller.signal.aborted) return;
        setLoaded({
          filterKey,
          token,
          items: response.data,
          cursor: response.page.has_more ? response.page.next_cursor : null,
          error: null,
          moreError: null,
          updatedAt: now(),
        });
      },
      (failure: unknown) => {
        if (controller.signal.aborted) return;
        setLoaded((previous) => {
          const same = previous?.filterKey === filterKey;
          return {
            filterKey,
            token,
            items: same ? previous.items : [],
            cursor: same ? previous.cursor : null,
            error: asError(failure),
            moreError: null,
            updatedAt: same ? previous.updatedAt : null,
          };
        });
      },
    );
    return () => {
      controller.abort();
    };
  }, [client, filterKey, token, now]);

  const current = loaded?.filterKey === filterKey ? loaded : null;
  const cursor = current?.cursor ?? null;

  const loadMore = useCallback(() => {
    if (cursor === null || loadingMore) return;
    const controller = new AbortController();
    moreController.current = controller;
    setLoadingMore(true);
    const filtersNow = JSON.parse(filterKey) as IncidentFilters;
    listIncidents(client, filtersToQuery(filtersNow, cursor), controller.signal)
      .then(
        (response) => {
          if (controller.signal.aborted) return;
          setLoaded((previous) =>
            previous === null
              ? previous
              : {
                  ...previous,
                  items: [...previous.items, ...response.data],
                  cursor: response.page.has_more ? response.page.next_cursor : null,
                  moreError: null,
                },
          );
        },
        (failure: unknown) => {
          if (controller.signal.aborted) return;
          setLoaded((previous) =>
            previous === null ? previous : { ...previous, moreError: asError(failure) },
          );
        },
      )
      .finally(() => {
        setLoadingMore(false);
      });
  }, [client, cursor, filterKey, loadingMore]);

  const refresh = useCallback(() => {
    setAttempt((value) => value + 1);
  }, []);

  const items = current?.items ?? [];
  const error = current?.token === token ? current.error : null;
  return {
    items,
    hasMore: cursor !== null,
    loading: loaded?.token !== token,
    loadingMore,
    error,
    moreError: current?.moreError ?? null,
    stale: error !== null && items.length > 0,
    updatedAt: current?.updatedAt ?? null,
    loadMore,
    refresh,
  };
}
