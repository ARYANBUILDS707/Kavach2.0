// MVP-F1 routes only. The analyst pages (MVP-F2) and `/analyze` (MVP-F3, after MVP-B4) are not
// registered yet, so no route or navigation item implies a feature that does not exist.
import { Route, Routes } from "react-router";

import { LoginPage } from "../features/auth/LoginPage";
import { WorkspacePending } from "../features/workspace/WorkspacePending";
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
        <Route index element={<WorkspacePending />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
