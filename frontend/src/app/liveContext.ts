import { createContext, useContext } from "react";

export type LiveStatus = "connecting" | "live" | "offline";

export interface LiveState {
  status: LiveStatus;
  /** The newest scoring cycle seen (from the stream, or the fleet figures before that). */
  lastCycle: Date | null;
}

export const LiveContext = createContext<LiveState>({ status: "connecting", lastCycle: null });

export function useLive(): LiveState {
  return useContext(LiveContext);
}

/** Polite screen-reader announcements (WCAG 4.1.3, PDS §8). */
export const AnnounceContext = createContext<(message: string) => void>(() => undefined);

export function useAnnounce(): (message: string) => void {
  return useContext(AnnounceContext);
}

/** Which cached reads an event makes stale, by the first part of their query keys. */
export const INVALIDATES: Record<string, readonly string[]> = {
  "score.updated": ["fleet", "assets", "models", "scores", "health", "sensors"],
  "alert.changed": ["alerts", "fleet", "assets", "models"],
  "job.progress": ["jobs", "models"],
};
