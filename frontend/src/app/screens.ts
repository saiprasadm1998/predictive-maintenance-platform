/**
 * The route table. Every screen belongs to one sidebar entry (`nav`), and every screen state
 * that matters lives in the URL so notifications and case records open the exact view.
 */

export type NavKey =
  | "ov"
  | "un"
  | "eq"
  | "al"
  | "an"
  | "se"
  | "ca"
  | "cf"
  | "hi"
  | "at"
  | "er"
  | "tg"
  | "hd"
  | "mo"
  | "fm"
  | "dq"
  | "ig"
  | "nt"
  | "api"
  | "us"
  | "re"
  | "au";

export interface Screen {
  id: string;
  path: string; // React Router pattern
  title: string;
  nav: NavKey;
}

export const SCREENS: readonly Screen[] = [
  { id: "overview", path: "/fleet", title: "Overview", nav: "ov" },
  { id: "units", path: "/units", title: "Unit view", nav: "un" },
  { id: "unit", path: "/units/:assetId", title: "Unit view", nav: "un" },
  { id: "equipment", path: "/equipment", title: "Equipment", nav: "eq" },
  { id: "alerts", path: "/alerts", title: "Alerts", nav: "al" },
  { id: "analysis-pick", path: "/assets", title: "Equipment analysis", nav: "an" },
  { id: "analysis", path: "/assets/:assetId", title: "Equipment analysis", nav: "an" },
  { id: "sensors", path: "/sensors", title: "Sensor health", nav: "se" },
  { id: "cases", path: "/cases", title: "Cases", nav: "ca" },
  { id: "case", path: "/cases/:caseId", title: "Case", nav: "ca" },
  { id: "setup", path: "/setup", title: "Setup overview", nav: "cf" },
  { id: "hierarchy", path: "/setup/hierarchy", title: "Plant hierarchy", nav: "hi" },
  { id: "types", path: "/setup/types", title: "Equipment types and roles", nav: "at" },
  { id: "register", path: "/setup/equipment", title: "Equipment register", nav: "er" },
  { id: "add-equipment", path: "/setup/equipment/new", title: "Add equipment", nav: "er" },
  { id: "tags", path: "/setup/tags", title: "Tags and mapping", nav: "tg" },
  { id: "history", path: "/setup/history", title: "Historical data", nav: "hd" },
  { id: "upload", path: "/setup/history/upload", title: "Upload history", nav: "hd" },
  { id: "models", path: "/models", title: "Models", nav: "mo" },
  { id: "builder", path: "/models/:modelId/build/:step", title: "New model", nav: "mo" },
  { id: "version", path: "/models/:modelId/versions/:version", title: "Model version", nav: "mo" },
  { id: "library", path: "/library", title: "Failure modes", nav: "fm" },
  { id: "dq", path: "/setup/data-quality", title: "Data-quality rules", nav: "dq" },
  { id: "ingestion", path: "/system/ingestion", title: "Ingestion health", nav: "ig" },
  { id: "notifications", path: "/system/notifications", title: "Notifications", nav: "nt" },
  { id: "users", path: "/system/users", title: "Users and access", nav: "us" },
  { id: "retention", path: "/system/retention", title: "Retention", nav: "re" },
  { id: "audit", path: "/system/audit", title: "Audit log", nav: "au" },
  { id: "coverage", path: "/coverage", title: "Use-case coverage", nav: "cf" },
];

export interface NavLink {
  key: NavKey;
  label: string;
  to: string;
  icon: string; // SVG path data, 24 x 24
}

export interface NavGroup {
  label: string;
  links: NavLink[];
}

export const NAV: readonly NavGroup[] = [
  {
    label: "Find problems",
    links: [
      {
        key: "ov",
        label: "Overview",
        to: "/fleet",
        icon: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
      },
      {
        key: "un",
        label: "Unit view",
        to: "/units",
        icon: "M3 20h18M5 20V9l4-3v14M9 20V6l6 4v10M15 20v-8l4 2v6",
      },
      { key: "eq", label: "Equipment", to: "/equipment", icon: "M4 8h16v11H4zM8 8V5h8v3M4 13h16" },
      { key: "al", label: "Alerts", to: "/alerts", icon: "M12 3l9 16H3zM12 10v4M12 17v.5" },
    ],
  },
  {
    label: "Check equipment",
    links: [
      { key: "an", label: "Equipment analysis", to: "/assets", icon: "M3 12h4l2-6 4 12 2-6h6" },
      { key: "se", label: "Sensor health", to: "/sensors", icon: "M5 18a7 7 0 1 1 14 0M12 18l4-5" },
    ],
  },
  {
    label: "Act",
    links: [{ key: "ca", label: "Cases", to: "/cases", icon: "M4 7h6l2 2h8v10H4z" }],
  },
  {
    label: "Set up",
    links: [
      { key: "cf", label: "Setup overview", to: "/setup", icon: "M5 12l4 4 10-10" },
      {
        key: "hi",
        label: "Plant hierarchy",
        to: "/setup/hierarchy",
        icon: "M12 3v5M12 8H6v5M12 8h6v5M4 13h4v6H4zM16 13h4v6h-4z",
      },
      {
        key: "at",
        label: "Equipment types and roles",
        to: "/setup/types",
        icon: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM16.5 13v7M13 16.5h7",
      },
      {
        key: "er",
        label: "Equipment register",
        to: "/setup/equipment",
        icon: "M5 4h14v16H5zM9 9h6M9 13h6M9 17h3",
      },
      {
        key: "tg",
        label: "Tags and mapping",
        to: "/setup/tags",
        icon: "M4 12l8-8h8v8l-8 8zM16 8v.5",
      },
      {
        key: "hd",
        label: "Historical data",
        to: "/setup/history",
        icon: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
      },
      { key: "mo", label: "Models", to: "/models", icon: "M4 18l5-7 4 4 7-9" },
      {
        key: "fm",
        label: "Failure modes",
        to: "/library",
        icon: "M5 4h10l4 4v12H5zM9 12h6M9 16h4",
      },
      {
        key: "dq",
        label: "Data-quality rules",
        to: "/setup/data-quality",
        icon: "M4 6h16M7 12h10M10 18h4",
      },
    ],
  },
  {
    label: "System",
    links: [
      {
        key: "ig",
        label: "Ingestion health",
        to: "/system/ingestion",
        icon: "M4 12h4l3-7 4 14 3-7h2",
      },
      {
        key: "nt",
        label: "Notifications",
        to: "/system/notifications",
        icon: "M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 20a2 2 0 0 0 4 0",
      },
      {
        key: "us",
        label: "Users and access",
        to: "/system/users",
        icon: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM3 20a6 6 0 0 1 12 0M16 4.5a3.5 3.5 0 0 1 0 6.5M18 14a6 6 0 0 1 3 6",
      },
      {
        key: "re",
        label: "Retention",
        to: "/system/retention",
        icon: "M12 3a9 9 0 1 0 9 9M12 7v5l3 2M21 3v6h-6",
      },
      {
        key: "au",
        label: "Audit log",
        to: "/system/audit",
        icon: "M6 3h9l3 3v15H6zM9 9h6M9 13h6M9 17h4",
      },
    ],
  },
];

/** Paths of the previous navigation, kept so bookmarks and e-mailed links still open. */
export const REDIRECTS: Readonly<Record<string, string>> = {
  "/admin/registry?tab=hierarchy": "/setup/hierarchy",
  "/admin/registry?tab=types": "/setup/types",
  "/admin/registry?tab=tags": "/setup/tags",
  "/admin/registry?tab=unmapped": "/setup/tags?tab=unmapped",
  "/admin/registry?tab=history": "/setup/history",
  "/admin/registry?tab=import": "/setup/hierarchy?import=1",
  "/admin/registry": "/setup",
  "/admin?tab=users": "/system/users",
  "/admin?tab=keys": "/system/users?tab=keys",
  "/admin?tab=rules": "/setup/data-quality",
  "/admin?tab=retention": "/system/retention",
  "/admin?tab=ingestion": "/system/ingestion",
  "/admin?tab=audit": "/system/audit",
  "/admin?tab=notifications": "/system/notifications",
  "/admin?tab=notification-log": "/system/notifications?tab=log",
  "/admin": "/system/users",
};
