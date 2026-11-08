// Internal paths a sign-in may return to. `next` comes from the URL, so it is untrusted: only
// same-origin paths of known shapes are accepted, anything else falls back to the overview.
const KNOWN_PATHS = [
  /^\/$/,
  /^\/incidents$/,
  /^\/incidents\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
  /^\/system$/,
  /^\/analyze$/,
];
const SAFE_QUERY = /^\?[A-Za-z0-9=&_.:%+-]{0,512}$/;

export const HOME = "/";

export function safeNext(value: string | null): string {
  if (value === null) return HOME;
  const queryStart = value.indexOf("?");
  const path = queryStart === -1 ? value : value.slice(0, queryStart);
  const query = queryStart === -1 ? "" : value.slice(queryStart);
  if (!KNOWN_PATHS.some((pattern) => pattern.test(path))) return HOME;
  if (query !== "" && !SAFE_QUERY.test(query)) return HOME;
  return value;
}

export function loginPath(next: string): string {
  return next === HOME ? "/login" : `/login?next=${encodeURIComponent(next)}`;
}
