// Every internal path lives here. The public site (`/`, `/examples`) is static and makes no API
// calls; the operator console and its sign-in live under `/admin`, which nothing public links to.
export const PUBLIC_HOME = "/";
export const EXAMPLES = "/examples";

export const ADMIN_HOME = "/admin";
export const ADMIN_LOGIN = "/admin/login";
export const ADMIN_INCIDENTS = "/admin/incidents";
export const ADMIN_SYSTEM = "/admin/system";
export const ADMIN_ANALYZE = "/admin/analyze";

export function adminIncident(id: string): string {
  return `${ADMIN_INCIDENTS}/${id}`;
}

// Internal paths a sign-in may return to. `next` comes from the URL, so it is untrusted: only
// same-origin console paths of known shapes are accepted, anything else falls back to the console
// overview.
const KNOWN_PATHS = [
  /^\/admin$/,
  /^\/admin\/incidents$/,
  /^\/admin\/incidents\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
  /^\/admin\/system$/,
  /^\/admin\/analyze$/,
];
const SAFE_QUERY = /^\?[A-Za-z0-9=&_.:%+-]{0,512}$/;

export function safeNext(value: string | null): string {
  if (value === null) return ADMIN_HOME;
  const queryStart = value.indexOf("?");
  const path = queryStart === -1 ? value : value.slice(0, queryStart);
  const query = queryStart === -1 ? "" : value.slice(queryStart);
  if (!KNOWN_PATHS.some((pattern) => pattern.test(path))) return ADMIN_HOME;
  if (query !== "" && !SAFE_QUERY.test(query)) return ADMIN_HOME;
  return value;
}

export function loginPath(next: string): string {
  return next === ADMIN_HOME ? ADMIN_LOGIN : `${ADMIN_LOGIN}?next=${encodeURIComponent(next)}`;
}
