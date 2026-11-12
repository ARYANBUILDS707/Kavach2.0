// Two separate areas. The public site (`/`, `/examples`) is static: no session, no API calls, no
// accounts. The operator console lives under `/admin`: sign-in, session restore and every page
// behind it, with `/admin/analyze` limited to admins. The UI guards are convenience only; the
// server enforces the session, role, CSRF, Origin and source on every request (API.md).
import { Navigate, Outlet, Route, Routes } from "react-router";

import { AnalyzePage } from "../features/analyze/AnalyzePage";
import { LoginPage } from "../features/auth/LoginPage";
import { IncidentDetailPage } from "../features/incidents/IncidentDetailPage";
import { IncidentListPage } from "../features/incidents/IncidentListPage";
import { LandingPage } from "../features/landing/LandingPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { ExamplesPage } from "../features/public/ExamplesPage";
import { SystemPage } from "../features/system/SystemPage";
import { AppShell } from "./AppShell";
import { RequireRole, RequireSession } from "./guards";
import { NotFoundPage } from "./NotFoundPage";
import { ADMIN_LOGIN, PUBLIC_HOME } from "./routes";
import { SessionProvider } from "./SessionProvider";

/** The session is only ever looked up here, so a public visit never calls /auth/session. */
function AdminArea({ now }: { now: (() => number) | undefined }) {
  return (
    <SessionProvider {...(now === undefined ? {} : { now })}>
      {/* A hint for crawlers; it protects nothing. Access control is enforced by the server. */}
      <meta name="robots" content="noindex, nofollow" />
      <Outlet />
    </SessionProvider>
  );
}

export function AppRouter({ now }: { now?: () => number } = {}) {
  return (
    <Routes>
      <Route index element={<LandingPage />} />
      <Route path="examples" element={<ExamplesPage />} />
      {/* Old addresses keep working without leading anywhere public that requires a login. */}
      <Route path="welcome" element={<Navigate to={PUBLIC_HOME} replace />} />
      <Route path="login" element={<Navigate to={ADMIN_LOGIN} replace />} />
      <Route path="admin" element={<AdminArea now={now} />}>
        <Route path="login" element={<LoginPage />} />
        <Route
          element={
            <RequireSession>
              <AppShell />
            </RequireSession>
          }
        >
          <Route index element={<OverviewPage />} />
          <Route path="incidents" element={<IncidentListPage />} />
          <Route path="incidents/:incidentId" element={<IncidentDetailPage />} />
          <Route path="system" element={<SystemPage />} />
          <Route
            path="analyze"
            element={
              <RequireRole roles={["admin"]}>
                <AnalyzePage />
              </RequireRole>
            }
          />
        </Route>
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
