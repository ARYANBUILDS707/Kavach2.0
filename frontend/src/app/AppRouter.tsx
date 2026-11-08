// MVP-F2 routes. `/analyze` (MVP-F3, after MVP-B4) is not registered yet, so no route or
// navigation item implies a feature that does not exist.
import { Route, Routes } from "react-router";

import { LoginPage } from "../features/auth/LoginPage";
import { IncidentDetailPage } from "../features/incidents/IncidentDetailPage";
import { IncidentListPage } from "../features/incidents/IncidentListPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { SystemPage } from "../features/system/SystemPage";
import { AppShell } from "./AppShell";
import { RequireSession } from "./guards";
import { NotFoundPage } from "./NotFoundPage";

export function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
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
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
