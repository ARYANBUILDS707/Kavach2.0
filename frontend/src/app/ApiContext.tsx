import { createContext, useContext, type ReactNode } from "react";

import type { ApiClient } from "../lib/api/client";

const ApiContext = createContext<ApiClient | null>(null);

/** Provides the single API client; tests pass a client built on a fake fetch. */
export function ApiProvider({ client, children }: { client: ApiClient; children: ReactNode }) {
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (client === null) throw new Error("useApi must be used inside ApiProvider");
  return client;
}
