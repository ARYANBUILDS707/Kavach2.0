// Header (KAVACH, environment label, the user's name and role, sign-out), skip link and main
// landmark (DESIGN.md "App shell"). Navigation items arrive with the pages they lead to.
import { useState } from "react";
import { Outlet } from "react-router";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import type { ApiError } from "../lib/api/errors";
import { useSession } from "./SessionProvider";

const ROLE_LABELS = { viewer: "Viewer", analyst: "Analyst", admin: "Admin" } as const;

export function AppShell() {
  const { state, expiringSoon, signOut } = useSession();
  const [pending, setPending] = useState(false);
  const [signOutError, setSignOutError] = useState<ApiError | null>(null);
  if (state.status !== "signedIn") return null;
  const { user } = state.session;

  async function handleSignOut() {
    setPending(true);
    setSignOutError(null);
    const error = await signOut();
    setPending(false);
    setSignOutError(error);
  }

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="shell-header">
        <span className="shell-brand">KAVACH</span>
        <span className="demo-label">Controlled demonstration</span>
        <span className="shell-meta">
          {user.display_name} · {ROLE_LABELS[user.role]}
        </span>
        <Button
          variant="secondary"
          pending={pending}
          pendingLabel="Signing out…"
          onClick={() => {
            void handleSignOut();
          }}
        >
          Sign out
        </Button>
      </header>
      <main id="main" className="shell-main" tabIndex={-1}>
        {expiringSoon ? (
          <Banner>
            Your session ends in less than five minutes. Save your place; you will need to sign in
            again.
          </Banner>
        ) : null}
        {signOutError ? (
          <Banner tone="error">
            Sign-out could not be confirmed, so your session may still be active. Try again.
          </Banner>
        ) : null}
        <Outlet />
      </main>
    </>
  );
}
