// The documented contract paths used by MVP-F1/F2. No Authorization header ever; the session
// cookie is the only credential.
import type { ApiClient } from "./client";
import type {
  IncidentDetailResponse,
  IncidentListQuery,
  IncidentListResponse,
  LoginRequest,
  ModelsResponse,
  SessionResponse,
} from "./types";

function withSignal(signal: AbortSignal | undefined) {
  return signal === undefined ? {} : { signal };
}

export function getSession(client: ApiClient, signal?: AbortSignal): Promise<SessionResponse> {
  return client.get<SessionResponse>("/api/v1/auth/session", withSignal(signal));
}

export async function login(client: ApiClient, request: LoginRequest): Promise<SessionResponse> {
  const response = await client.post<SessionResponse>("/api/v1/auth/login", request);
  if (response === null) throw new Error("Sign-in returned no session");
  return response;
}

export async function logout(client: ApiClient, csrfToken: string): Promise<void> {
  await client.post<null>("/api/v1/auth/logout", {}, { csrfToken });
}

export function getModels(client: ApiClient, signal?: AbortSignal): Promise<ModelsResponse> {
  return client.get<ModelsResponse>("/api/v1/system/models", withSignal(signal));
}

export function listIncidents(
  client: ApiClient,
  query: IncidentListQuery,
  signal?: AbortSignal,
): Promise<IncidentListResponse> {
  return client.get<IncidentListResponse>("/api/v1/incidents", {
    query: { ...query },
    ...withSignal(signal),
  });
}

export function getIncident(
  client: ApiClient,
  incidentId: string,
  signal?: AbortSignal,
): Promise<IncidentDetailResponse> {
  return client.get<IncidentDetailResponse>(
    `/api/v1/incidents/${encodeURIComponent(incidentId)}`,
    withSignal(signal),
  );
}
