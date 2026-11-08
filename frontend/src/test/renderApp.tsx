// TEST ONLY: renders the real router and providers on a scripted fetch.
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";

import { ApiProvider } from "../app/ApiContext";
import { AppRouter } from "../app/AppRouter";
import { SessionProvider } from "../app/SessionProvider";
import { createClient } from "../lib/api/client";
import { fakeFetch, type Scripted } from "./fakeFetch";

export function renderApp(path: string, script: Scripted[], now?: () => number) {
  const fake = fakeFetch(...script);
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
  return { ...view, requests: fake.requests, client };
}
