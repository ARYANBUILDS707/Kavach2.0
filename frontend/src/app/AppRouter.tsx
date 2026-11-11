// MVP-F3 routes. `/analyze` is admin-only in the UI; the server enforces the role, CSRF,
// Origin and source on every submission regardless (MVP-B4).
import { Route, Routes } from "react-router";

import { AnalyzePage } from "../features/analyze/AnalyzePage";
import { LoginPage } from "../features/auth/LoginPage";
import { IncidentDetailPage } from "../features/incidents/IncidentDetailPage";
import { IncidentListPage } from "../features/incidents/IncidentListPage";
import { LandingPage } from "../features/landing/LandingPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { SystemPage } from "../features/system/SystemPage";
import { AppShell } from "./AppShell";
import { RequireRole, RequireSession } from "./guards";
import { NotFoundPage } from "./NotFoundPage";

export function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      {/* Public product page: no session, no API calls, no sign-up. */}
      <Route path="/welcome" element={<LandingPage />} />
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
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
