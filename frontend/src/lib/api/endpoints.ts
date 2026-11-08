// The MVP-F1 endpoints. Only the documented contract paths; no Authorization header ever.
import type { ApiClient } from "./client";
import type { LoginRequest, SessionResponse } from "./types";

export function getSession(client: ApiClient, signal?: AbortSignal): Promise<SessionResponse> {
  return client.get<SessionResponse>(
    "/api/v1/auth/session",
    signal === undefined ? {} : { signal },
  );
}

export async function login(client: ApiClient, request: LoginRequest): Promise<SessionResponse> {
  const response = await client.post<SessionResponse>("/api/v1/auth/login", request);
  if (response === null) throw new Error("Sign-in returned no session");
  return response;
}

export async function logout(client: ApiClient, csrfToken: string): Promise<void> {
  await client.post<null>("/api/v1/auth/logout", {}, { csrfToken });
}
