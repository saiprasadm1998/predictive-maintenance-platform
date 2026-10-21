import { formatDateTime, formatIso, formatTime } from "../app/format";
import { useLive } from "../app/liveContext";

/** PDS §2.2: whether updates are live, and the time of the last scoring cycle. */
export function LiveIndicator() {
  const { status, lastCycle } = useLive();
  const today =
    lastCycle && formatDateTime(lastCycle).slice(0, 6) === formatDateTime(new Date()).slice(0, 6);
  const when = lastCycle ? (today ? formatTime(lastCycle) : formatDateTime(lastCycle)) : null;
  const text =
    status === "live"
      ? `Live${when ? ` · scored ${when}` : " · not scored yet"}`
      : status === "connecting"
        ? "Connecting…"
        : "Offline · reconnecting";
  return (
    <span
      className={`control live${status === "live" ? " live-on" : ""}`}
      title={lastCycle ? `Last scoring cycle ${formatIso(lastCycle)}` : undefined}
    >
      <span className="live-dot" aria-hidden="true" />
      {text}
    </span>
  );
}
