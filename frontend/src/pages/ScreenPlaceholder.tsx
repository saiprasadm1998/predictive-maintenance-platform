import { useParams } from "react-router-dom";

import type { Screen } from "../app/screens";
import { useTimeRange } from "../app/timeRange";

/** Stands in for a screen until its sub-phase builds it, showing the state it was opened
 * with, so deep links can be checked now. */
export function ScreenPlaceholder({ screen }: { screen: Screen }) {
  const params = useParams();
  const { range } = useTimeRange();
  const entries = Object.entries(params);
  return (
    <section className="panel placeholder" aria-labelledby="placeholder-title">
      <h2 id="placeholder-title" className="panel-title">
        {screen.id} · {screen.title}
      </h2>
      <p>
        This screen is built in sub-phase {screen.phase}
        {screen.phase === "Stretch" ? " (stretch goal)" : ""}.
      </p>
      <dl className="placeholder-state">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{value}</dd>
          </div>
        ))}
        <div>
          <dt>time range</dt>
          <dd>
            {range.preset ?? "custom"} · {range.from.toISOString()} to {range.to.toISOString()}
          </dd>
        </div>
      </dl>
    </section>
  );
}
