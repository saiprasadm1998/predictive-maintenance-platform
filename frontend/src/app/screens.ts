/**
 * The route table (PDS §4, §9). Screen identifiers SCR-nn are the ones used in the design
 * spec and in test cases; routes mirror them and carry every screen state in the URL
 * (PDS §2.2) so notifications and case records open the exact view.
 */

export type NavSection = "fleet" | "alerts" | "cases" | "models" | "sensors" | "library" | "admin";

export interface Screen {
  id: string; // SCR-nn
  path: string; // React Router pattern
  title: string;
  section: NavSection;
  phase: string; // implementation plan sub-phase that builds it
}

export const SCREENS: readonly Screen[] = [
  { id: "SCR-01", path: "/fleet", title: "Fleet overview", section: "fleet", phase: "6.2" },
  {
    id: "SCR-08",
    path: "/units/:assetId",
    title: "Area / unit view",
    section: "fleet",
    phase: "6.2",
  },
  {
    id: "SCR-03",
    path: "/assets/:assetId",
    title: "Asset analysis",
    section: "fleet",
    phase: "6.3",
  },
  {
    id: "SCR-04",
    path: "/assets/:assetId/diagnostics",
    title: "Diagnostics and forecast",
    section: "fleet",
    phase: "8.2",
  },
  { id: "SCR-02", path: "/alerts", title: "Alert list", section: "alerts", phase: "6.4" },
  { id: "SCR-09", path: "/cases", title: "Cases", section: "cases", phase: "8.4" },
  { id: "SCR-05", path: "/cases/:caseId", title: "Case detail", section: "cases", phase: "8.4" },
  { id: "SCR-10", path: "/models", title: "Model management", section: "models", phase: "6.5" },
  {
    id: "SCR-06",
    path: "/models/:modelId/build/:step",
    title: "Model builder",
    section: "models",
    phase: "6.5",
  },
  {
    id: "SCR-11",
    path: "/models/:modelId/versions/:version",
    title: "Model version",
    section: "models",
    phase: "6.5",
  },
  { id: "SCR-07", path: "/sensors", title: "Sensor health", section: "sensors", phase: "6.6" },
  {
    id: "SCR-12",
    path: "/library",
    title: "Failure-mode library",
    section: "library",
    phase: "8.2",
  },
  { id: "SCR-14", path: "/admin", title: "Administration", section: "admin", phase: "6.6" },
  {
    id: "SCR-13",
    path: "/admin/registry",
    title: "Registry and import",
    section: "admin",
    phase: "6.6",
  },
  { id: "SCR-15", path: "/reports", title: "Reports", section: "admin", phase: "Stretch" },
  // Development only: every shared component with sample data (not in production builds).
  ...(import.meta.env.DEV
    ? [
        {
          id: "DEV",
          path: "/design",
          title: "Design system",
          section: "admin" as const,
          phase: "6.1",
        },
      ]
    : []),
];

export interface NavItem {
  section: NavSection;
  label: string;
  to: string;
}

/** PDS §2.2: the left navigation rail, in this order. */
export const NAV_ITEMS: readonly NavItem[] = [
  { section: "fleet", label: "Fleet", to: "/fleet" },
  { section: "alerts", label: "Alerts", to: "/alerts" },
  { section: "cases", label: "Cases", to: "/cases" },
  { section: "models", label: "Models", to: "/models" },
  { section: "sensors", label: "Sensor health", to: "/sensors" },
  { section: "library", label: "Library", to: "/library" },
  { section: "admin", label: "Administration", to: "/admin" },
];
