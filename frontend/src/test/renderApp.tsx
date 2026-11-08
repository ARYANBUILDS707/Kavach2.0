// TEST ONLY: renders the real router and providers on a scripted fetch.
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import { ApiProvider } from "../app/ApiContext";
import { AppRouter } from "../app/AppRouter";
import { SessionProvider } from "../app/SessionProvider";
import { createClient } from "../lib/api/client";
import { EMPTY_PAGE, MODELS_DISABLED, fakeFetch, json, router, type Scripted } from "./fakeFetch";

/** `authScript` answers the /auth/* calls in order; dashboard reads default to a disabled model
 * and an empty incident list unless `routes` scripts them. */
export function renderApp(
  path: string,
  authScript: Scripted[],
  now?: () => number,
  routes: Record<string, Scripted | Scripted[]> = {},
) {
  let authIndex = 0;
  const auth: Scripted = (request) => {
    const step = authScript[Math.min(authIndex, authScript.length - 1)];
    authIndex += 1;
    if (step === undefined) throw new Error("renderApp: no auth response scripted");
    return step(request);
  };
  const dispatch = router({
    "/api/v1/auth/session": auth,
    "/api/v1/auth/login": auth,
    "/api/v1/auth/logout": auth,
    "/api/v1/system/models": () => json(200, MODELS_DISABLED),
    "/api/v1/incidents": () => json(200, EMPTY_PAGE),
    ...routes,
  });
  const fake = fakeFetch(dispatch);
  const client = createClient({ fetch: fake.fetch, sleep: () => Promise.resolve() });
  const view = render(
    <ApiProvider client={client}>
      <SessionProvider {...(now === undefined ? {} : { now })}>
        <MemoryRouter initialEntries={[path]}>
          <AppRouter />
        </MemoryRouter>
      </SessionProvider>
    </ApiProvider>,
  );
  const callsTo = (target: string) => fake.requests.filter((r) => r.url.split("?")[0] === target);
  return { ...view, requests: fake.requests, callsTo, client };
}
