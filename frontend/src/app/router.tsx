import { type ReactNode, Suspense, lazy } from "react";
import { Navigate, type RouteObject } from "react-router-dom";

import { AppShell } from "../layout/AppShell";
import { FleetPage } from "../pages/fleet/FleetPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { ScreenPlaceholder } from "../pages/ScreenPlaceholder";
import { SignInPage } from "../pages/SignInPage";
import { RequireAuth } from "./auth";
import { SCREENS } from "./screens";

// Screens with charts are loaded on demand, so the chart library stays out of the first load.
const UnitPage = lazy(() =>
  import("../pages/fleet/UnitPage").then((m) => ({ default: m.UnitPage })),
);

const AssetPage = lazy(() =>
  import("../pages/asset/AssetPage").then((m) => ({ default: m.AssetPage })),
);

const AlertsPage = lazy(() =>
  import("../pages/alerts/AlertsPage").then((m) => ({ default: m.AlertsPage })),
);

const ModelsPage = lazy(() =>
  import("../pages/models/ModelsPage").then((m) => ({ default: m.ModelsPage })),
);
const VersionPage = lazy(() =>
  import("../pages/models/VersionPage").then((m) => ({ default: m.VersionPage })),
);

const BuilderPage = lazy(() =>
  import("../pages/models/BuilderPage").then((m) => ({ default: m.BuilderPage })),
);

const RegistryPage = lazy(() =>
  import("../pages/registry/RegistryPage").then((m) => ({ default: m.RegistryPage })),
);
const AdminPage = lazy(() =>
  import("../pages/admin/AdminPage").then((m) => ({ default: m.AdminPage })),
);

const BUILT: Record<string, ReactNode> = {
  "SCR-13": <RegistryPage />,
  "SCR-14": <AdminPage />,
  "SCR-06": <BuilderPage />,
  "SCR-10": <ModelsPage />,
  "SCR-11": <VersionPage />,
  "SCR-02": <AlertsPage />,
  "SCR-01": <FleetPage />,
  "SCR-08": <UnitPage />,
  "SCR-03": <AssetPage />,
};

// Development only, and loaded on demand so its charts never reach the main bundle.
const DesignPage = import.meta.env.DEV
  ? lazy(() => import("../pages/DesignPage").then((m) => ({ default: m.DesignPage })))
  : null;

export const routes: RouteObject[] = [
  { path: "/sign-in", element: <SignInPage /> },
  {
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/fleet" replace /> },
      ...SCREENS.filter((screen) => screen.id !== "DEV").map((screen) => ({
        path: screen.path,
        element: (
          <Suspense fallback={<p className="muted">Loading…</p>}>
            {BUILT[screen.id] ?? <ScreenPlaceholder key={screen.id} screen={screen} />}
          </Suspense>
        ),
      })),
      ...(DesignPage
        ? [
            {
              path: "/design",
              element: (
                <Suspense fallback={<p className="muted">Loading…</p>}>
                  <DesignPage />
                </Suspense>
              ),
            },
          ]
        : []),
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];
