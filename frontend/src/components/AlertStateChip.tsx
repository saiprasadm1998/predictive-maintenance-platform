import { formatDuration } from "../app/format";
import { type AlertState, type Severity, needsAck, severityLook } from "./status";
import { StatusShape } from "./StatusShape";

const TEXT: Record<AlertState, string> = {
  "Active-Unacknowledged": "Active · unack",
  "Active-Acknowledged": "Active · ack",
  "RTN-Unacknowledged": "RTN · unack",
  Shelved: "Shelved",
  "Out of service": "Out of service",
  Normal: "Normal",
};

/**
 * State, severity and acknowledgement shown together (PDS §1, §3.2, ISA-18.2): the shape
 * gives the severity, the text the state; unacknowledged is bold, acknowledged regular;
 * shelved and out of service are grey, shelved with a clock badge and the time left.
 */
export function AlertStateChip({
  state,
  severity,
  shelvedUntil,
  now = new Date(),
}: {
  state: AlertState;
  severity: Severity;
  shelvedUntil?: Date | null;
  now?: Date;
}) {
  const look = severityLook(severity);
  const muted = state === "Shelved" || state === "Out of service" || state === "Normal";
  const tone = muted ? "unknown" : look.tone;
  const left = state === "Shelved" && shelvedUntil ? shelvedUntil.getTime() - now.getTime() : null;
  return (
    <span
      className={`chip chip-m tone-${tone}${needsAck(state) ? "" : " chip-regular"}`}
      data-status={state}
    >
      <span className="chip-shape-wrap">
        <StatusShape shape={look.shape} tone={tone} />
        {state === "Shelved" && (
          <svg className="chip-badge" width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
            <circle
              cx="4"
              cy="4"
              r="3.3"
              fill="var(--panel)"
              stroke="currentColor"
              strokeWidth="1"
            />
            <path d="M4 2.2V4h1.4" fill="none" stroke="currentColor" strokeWidth="0.9" />
          </svg>
        )}
      </span>
      <span className="chip-label">
        <span className="visually-hidden">{look.label} </span>
        {TEXT[state]}
        {left !== null && <span className="chip-detail"> · {formatDuration(left)} left</span>}
      </span>
    </span>
  );
}
