import { type ComponentType, type LazyExoticComponent, Suspense, lazy } from "react";
import { Navigate, type RouteObject, useLocation } from "react-router-dom";

import { AppShell } from "../layout/AppShell";
import { NotFoundPage } from "../pages/NotFoundPage";
import { Placeholder } from "../pages/Placeholder";
import { SignInPage } from "../pages/SignInPage";
import { RequireAuth } from "./auth";
import { REDIRECTS, SCREENS } from "./screens";

type Page = LazyExoticComponent<ComponentType>;
const page = <K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K): Page =>
  lazy(() => load().then((m) => ({ default: m[name] })));

/** Screen id -> page component. Pages load on demand, so charts stay out of the first load. */
const PAGES: Record<string, Page> = {
  overview: page(() => import("../pages/find/OverviewPage"), "OverviewPage"),
  units: page(() => import("../pages/find/UnitPage"), "UnitIndexPage"),
  unit: page(() => import("../pages/find/UnitPage"), "UnitPage"),
  equipment: page(() => import("../pages/find/EquipmentPage"), "EquipmentPage"),
  alerts: page(() => import("../pages/alerts/AlertsPage"), "AlertsPage"),
  "analysis-pick": page(() => import("../pages/check/AnalysisPage"), "AnalysisIndexPage"),
  sensors: page(() => import("../pages/check/SensorHealthPage"), "SensorHealthPage"),
  analysis: page(() => import("../pages/check/AnalysisPage"), "AnalysisPage"),
  cases: page(() => import("../pages/act/CasesPage"), "CasesPage"),
  case: page(() => import("../pages/act/CasePage"), "CasePage"),
  setup: page(() => import("../pages/setup/SetupOverviewPage"), "SetupOverviewPage"),
  register: page(() => import("../pages/setup/EquipmentRegisterPage"), "EquipmentRegisterPage"),
  "add-equipment": page(() => import("../pages/setup/AddEquipmentPage"), "AddEquipmentPage"),
  tags: page(() => import("../pages/setup/TagMappingPage"), "TagMappingPage"),
  history: page(() => import("../pages/setup/HistoryPage"), "HistoryPage"),
  upload: page(() => import("../pages/setup/HistoryPage"), "HistoryPage"),
  hierarchy: page(() => import("../pages/setup/HierarchyPage"), "HierarchyPage"),
  types: page(() => import("../pages/setup/TypesPage"), "TypesPage"),
  coverage: page(() => import("../pages/system/CoveragePage"), "CoveragePage"),
  models: page(() => import("../pages/Framed"), "ModelManagementPage"),
  version: page(() => import("../pages/Framed"), "ModelVersionPage"),
  builder: page(() => import("../pages/Framed"), "NewModelPage"),
  library: page(() => import("../pages/setup/FailureModesPage"), "FailureModesPage"),
  dq: page(() => import("../pages/Framed"), "DataQualityPage"),
  ingestion: page(() => import("../pages/system/IngestionPage"), "IngestionPage"),
  notifications: page(() => import("../pages/system/NotificationsPage"), "NotificationsPage"),
  users: page(() => import("../pages/system/UsersPage"), "UsersPage"),
  retention: page(() => import("../pages/system/RetentionPage"), "RetentionPage"),
  audit: page(() => import("../pages/system/AuditPage"), "AuditPage"),
};

/** Old links (the previous navigation) open their new place. */
function Redirector() {
  const location = useLocation();
  const exact = REDIRECTS[location.pathname + location.search];
  const byPath = REDIRECTS[location.pathname];
  const diagnostics = location.pathname.match(/^\/assets\/(\d+)\/diagnostics$/);
  if (diagnostics) return <Navigate to={`/assets/${diagnostics[1]}?tab=diagnosis`} replace />;
  if (exact ?? byPath) return <Navigate to={exact ?? byPath!} replace />;
  return <NotFoundPage />;
}

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
      ...SCREENS.map((screen) => {
        const Component = PAGES[screen.id];
        return {
          path: screen.path,
          element: (
            <Suspense fallback={<p className="sec s13">Loading…</p>}>
              {Component ? <Component /> : <Placeholder title={screen.title} />}
            </Suspense>
          ),
        };
      }),
      { path: "*", element: <Redirector /> },
    ],
  },
];
