import { formatDi, formatHealth } from "../app/format";
import type { Band } from "./status";
import { StatusChip } from "./StatusChip";

/**
 * The headline Health Score (PDS §5): a large integer with the band chip and the Deviation
 * Index below; the tooltip gives the limits. Worded "Health 41 · ALERT", never "41 % healthy".
 */
export function HealthScore({
  health,
  band,
  di,
  diWarning,
  diAlert,
  unknownReason,
}: {
  health: number | null;
  band: Band;
  di: number | null;
  diWarning?: number | null;
  diAlert?: number | null;
  unknownReason?: string | null;
}) {
  const limits =
    diWarning != null && diAlert != null
      ? `Warning at DI ${formatDi(diWarning)}, alert at DI ${formatDi(diAlert)}`
      : undefined;
  return (
    <div className="health-score" title={limits}>
      <div className="health-score-row">
        <span className="health-score-label">Health</span>
        <span className="health-score-value">{formatHealth(health)}</span>
        <StatusChip kind="band" value={band} detail={band === "Unknown" ? unknownReason : null} />
      </div>
      <div className="health-score-di muted">
        DI {formatDi(di)}
        {limits ? <span className="visually-hidden"> ({limits})</span> : null}
      </div>
    </div>
  );
}
