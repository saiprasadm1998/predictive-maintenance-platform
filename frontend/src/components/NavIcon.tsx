import type { NavSection } from "../app/screens";

/** PMP's own simple line icons for the navigation rail (PDS §1: original visual identity). */
const PATHS: Record<NavSection, string> = {
  fleet: "M4 20V10l4-3v13M10 20V6l5-3v17M17 20v-8l3-2v10M3 20h18",
  alerts: "M12 4 21 20H3Z M12 10v4 M12 17v.5",
  cases: "M5 4h10l4 4v12H5Z M15 4v4h4 M8 12h8 M8 16h6",
  models: "M3 17l5-6 4 3 4-7 5 5 M3 21h18",
  sensors: "M12 3a6 6 0 0 1 6 6c0 4-6 12-6 12S6 13 6 9a6 6 0 0 1 6-6Z M12 7v3 M12 12v.5",
  library: "M5 4h4v16H5Z M10 4h4v16h-4Z M15 5l3.5-1 3 15.5-3.5 1Z",
  admin:
    "M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z M12 2v3 M12 19v3 M2 12h3 M19 12h3 M4.9 4.9l2.1 2.1 M17 17l2.1 2.1 M4.9 19.1 7 17 M17 7l2.1-2.1",
};

export function NavIcon({ section }: { section: NavSection }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={PATHS[section]} />
    </svg>
  );
}
