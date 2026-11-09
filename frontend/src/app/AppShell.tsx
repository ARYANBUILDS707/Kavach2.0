// Header (KAVACH, environment label, SMS model status, the user's name and role, sign-out),
// navigation, skip link and main landmark (DESIGN.md "App shell"). Only pages the user may open
// are in the navigation: "Analyze SMS" appears for admins only.
import { useState } from "react";
import { NavLink, Outlet } from "react-router";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { ModelStatePill } from "../components/ModelStatePill";
import type { ApiError } from "../lib/api/errors";
import { ModelStatusProvider } from "./ModelStatusProvider";
import { useSession } from "./SessionProvider";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true, adminOnly: false },
  { to: "/incidents", label: "Incidents", end: false, adminOnly: false },
  { to: "/system", label: "System", end: false, adminOnly: false },
  { to: "/analyze", label: "Analyze SMS", end: false, adminOnly: true },
] as const;

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
    <ModelStatusProvider>
      <a className="skip-link" href="#main">
        Skip to main content
      </a>
      <header className="shell-header">
        <span className="shell-brand">KAVACH</span>
        <span className="demo-label">Controlled demonstration</span>
        <ModelStatePill />
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
      <div className="shell-body">
      <nav className="shell-nav" aria-label="Main">
        <ul>
          {NAV_ITEMS.filter((item) => !item.adminOnly || user.role === "admin").map((item) => (
            <li key={item.to}>
              <NavLink to={item.to} end={item.end}>
                {item.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
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
      </div>
    </ModelStatusProvider>
  );
}
