// Browser submission identifiers (owner decision B4-1, server-validated): `ui-` and `ui-sub-`
// plus a cryptographically random version-4 UUID. These are synthetic namespaces, never real
// subscriber identities.
const UUID_V4 = "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
export const BROWSER_EVENT_ID = new RegExp(`^ui-${UUID_V4}$`);
export const BROWSER_SUBSCRIBER_TOKEN = new RegExp(`^ui-sub-${UUID_V4}$`);

export function browserEventId(): string {
  return `ui-${crypto.randomUUID()}`;
}

export function browserSubscriberToken(): string {
  return `ui-sub-${crypto.randomUUID()}`;
}
