/**
 * Health 0–100 as a neutral bar with ticks at the warning and alert values (PDS §5). The
 * fill is never coloured by band: the band chip beside it carries the status (ISA-101).
 */
export function HealthBar({
  health,
  warningAt,
  alertAt,
  label = "Health",
}: {
  health: number | null;
  warningAt?: number | null;
  alertAt?: number | null;
  label?: string;
}) {
  if (health === null) {
    return (
      <span className="muted" aria-label={`${label}: no score`}>
        —
      </span>
    );
  }
  const value = Math.max(0, Math.min(100, Math.round(health)));
  return (
    <span className="health-bar-wrap">
      <span
        className="health-bar"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
      >
        <span className="health-bar-fill" style={{ width: `${value}%` }} />
        {warningAt != null && (
          <span className="health-bar-tick tick-warning" style={{ left: `${warningAt}%` }} />
        )}
        {alertAt != null && (
          <span className="health-bar-tick tick-alert" style={{ left: `${alertAt}%` }} />
        )}
      </span>
      <span className="health-bar-value">{value}</span>
    </span>
  );
}
