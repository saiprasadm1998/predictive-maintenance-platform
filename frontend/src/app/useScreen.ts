import { matchPath, useLocation } from "react-router-dom";

import { SCREENS, type Screen } from "./screens";

/** The screen the current URL shows (most specific pattern first), or null. */
export function findScreen(pathname: string): Screen | null {
  const ranked = [...SCREENS].sort((a, b) => b.path.length - a.path.length);
  return ranked.find((s) => matchPath({ path: s.path, end: true }, pathname)) ?? null;
}

export function useScreen(): Screen | null {
  return findScreen(useLocation().pathname);
}
