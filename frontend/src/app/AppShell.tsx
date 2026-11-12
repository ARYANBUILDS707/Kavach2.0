// Header (KAVACH, environment label, SMS model status, the user's name and role, theme and
// sign-out), navigation, skip link and main landmark. Only pages the user may open are in the
// navigation: "Analyze SMS" appears for admins only. Below 1200px the navigation and tools fold
// behind a menu button, which closes again on navigation or Escape.
import { useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import { Banner } from "../components/Banner";
import { Button } from "../components/Button";
import { ModelStatePill } from "../components/ModelStatePill";
import { SiteFooter } from "../components/SiteFooter";
import { ThemeToggle } from "../components/ThemeToggle";
import { Wordmark } from "../components/Wordmark";
import type { ApiError } from "../lib/api/errors";
import { ModelStatusProvider } from "./ModelStatusProvider";
import { ADMIN_ANALYZE, ADMIN_HOME, ADMIN_INCIDENTS, ADMIN_SYSTEM } from "./routes";
import { useSession } from "./SessionProvider";

const NAV_ITEMS = [
  { to: ADMIN_HOME, label: "Overview", end: true, adminOnly: false },
  { to: ADMIN_INCIDENTS, label: "Incidents", end: false, adminOnly: false },
  { to: ADMIN_SYSTEM, label: "System", end: false, adminOnly: false },
  { to: ADMIN_ANALYZE, label: "Analyze SMS", end: false, adminOnly: true },
] as const;

const ROLE_LABELS = { viewer: "Viewer", analyst: "Analyst", admin: "Admin" } as const;

export function AppShell() {
  const { state, expiringSoon, signOut } = useSession();
  const location = useLocation();
  const [pending, setPending] = useState(false);
  const [signOutError, setSignOutError] = useState<ApiError | null>(null);
  // The menu is open only for the location it was opened on, so navigating closes it.
  const [menuOpenAt, setMenuOpenAt] = useState<string | null>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  if (state.status !== "signedIn") return null;
  const { user } = state.session;
  const menuOpen = menuOpenAt === location.key;

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
      <header
        className="shell-header"
        onKeyDown={(event) => {
          // Escape closes the open menu from the toggle or anywhere inside it.
          if (event.key === "Escape" && menuOpen) {
            setMenuOpenAt(null);
            toggleRef.current?.focus();
          }
        }}
      >
        <div className="shell-bar">
          <Link to={ADMIN_HOME} className="wordmark-link" aria-label="KAVACH home">
            <Wordmark />
          </Link>
          <span className="demo-label">Controlled demonstration</span>
          <button
            ref={toggleRef}
            type="button"
            className="menu-toggle"
            aria-expanded={menuOpen}
            aria-controls="shell-panel"
            onClick={() => {
              setMenuOpenAt(menuOpen ? null : location.key);
            }}
          >
            <span className="menu-toggle-bars" aria-hidden="true" />
            Menu
          </button>
        </div>
        <div id="shell-panel" className="shell-panel" data-open={menuOpen}>
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
          <div className="shell-tools">
            <ModelStatePill />
            <span className="shell-user">
              <span className="shell-user-name" title={user.display_name}>
                {user.display_name}
              </span>{" "}
              · {ROLE_LABELS[user.role]}
            </span>
            <ThemeToggle />
            <Button
              variant="secondary"
              className="button-sm"
              pending={pending}
              pendingLabel="Signing out…"
              onClick={() => {
                void handleSignOut();
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
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
      <SiteFooter compact />
    </ModelStatusProvider>
  );
}
