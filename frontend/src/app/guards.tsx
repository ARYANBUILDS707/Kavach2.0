// Route guards are convenience only: the server enforces every permission (API.md).
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { Button } from "../components/Button";
import { LOADING, StateView, describeError } from "../components/StateView";
import type { Role } from "../lib/api/types";
import { loginPath, safeNext } from "./routes";
import { useSession } from "./SessionProvider";

export function RequireSession({ children }: { children: ReactNode }) {
  const { state, retry } = useSession();
  const location = useLocation();
  switch (state.status) {
    case "checking":
      return <StateView state={LOADING} />;
    case "unavailable":
      return (
        <StateView
          state={describeError(state.error)}
          action={<Button onClick={retry}>Try again</Button>}
        />
      );
    case "signedOut":
      return (
        <Navigate
          to={loginPath(safeNext(location.pathname + location.search))}
          replace
          state={{ reason: state.reason }}
        />
      );
    case "signedIn":
      return children;
  }
}

export function RequireRole({ roles, children }: { roles: readonly Role[]; children: ReactNode }) {
  const { state } = useSession();
  if (state.status !== "signedIn" || !roles.includes(state.session.user.role)) {
    return (
      <StateView
        pageHeading
        state={{
          kind: "forbidden",
          title: "You don't have access",
          message: "Your role does not allow this page.",
        }}
      />
    );
  }
  return children;
}
