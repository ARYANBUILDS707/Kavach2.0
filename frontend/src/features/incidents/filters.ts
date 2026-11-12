// Incident-list filters: the URL holds only filter values (never message content or cursors),
// every value is validated against the contract's enums, and dates are RFC 3339 with an offset.
import type { IncidentKind, IncidentListQuery, Tier } from "../../lib/api/types";

export type ChannelFilter = "sms" | "call" | "all";

export interface IncidentFilters {
  channel: ChannelFilter;
  kind: IncidentKind | null;
  tier: Tier | null;
  /** Inclusive, RFC 3339 UTC. */
  from: string | null;
  /** Exclusive, RFC 3339 UTC. */
  to: string | null;
}

export const DEFAULT_FILTERS: IncidentFilters = {
  channel: "sms",
  kind: null,
  tier: null,
  from: null,
  to: null,
};

export const PAGE_SIZE = 25;

const TIERS: readonly Tier[] = ["unknown", "low", "medium", "high", "critical"];
const KINDS: readonly IncidentKind[] = ["standalone", "pair"];
const CHANNELS: readonly ChannelFilter[] = ["sms", "call", "all"];
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$/;

function pick<T extends string>(value: string | null, allowed: readonly T[]): T | null {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : null;
}

function instant(value: string | null): string | null {
  if (value === null || !RFC3339.test(value)) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Unknown or malformed URL values are dropped, never sent to the API. */
export function filtersFromParams(params: URLSearchParams): IncidentFilters {
  return {
    channel: pick(params.get("channel"), CHANNELS) ?? "sms",
    kind: pick(params.get("kind"), KINDS),
    tier: pick(params.get("tier"), TIERS),
    from: instant(params.get("from")),
    to: instant(params.get("to")),
  };
}

export function filtersToParams(filters: IncidentFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.channel !== "sms") params.set("channel", filters.channel);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.tier) params.set("tier", filters.tier);
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  return params;
}

export function filtersToQuery(filters: IncidentFilters, cursor?: string): IncidentListQuery {
  const query: IncidentListQuery = { limit: PAGE_SIZE };
  if (filters.channel !== "all") query.channel = filters.channel;
  if (filters.kind) query.kind = filters.kind;
  if (filters.tier) query.tier = filters.tier;
  if (filters.from) query.from = filters.from;
  if (filters.to) query.to = filters.to;
  if (cursor !== undefined) query.cursor = cursor;
  return query;
}

export function isFiltered(filters: IncidentFilters): boolean {
  return filtersToParams(filters).toString() !== "";
}

/** A `datetime-local` value (local wall time) as RFC 3339 UTC, or null if empty or invalid. */
export function localInputToIso(value: string): string | null {
  if (value === "") return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** RFC 3339 as a `datetime-local` value in the viewer's zone. */
export function isoToLocalInput(iso: string | null): string {
  if (iso === null) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Client-side mirror of the server rule (`from` before `to`); the server stays authoritative. */
export function rangeError(from: string | null, to: string | null): string | null {
  if (from !== null && to !== null && Date.parse(from) >= Date.parse(to)) {
    return "The start must be before the end.";
  }
  return null;
}
