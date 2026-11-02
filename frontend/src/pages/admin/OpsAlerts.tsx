import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { fetchOpsAlerts } from "../../api/ops";

/** The built-in operational alerts (ARC §10.3) at the top of Administration: a stale
 * source, a scoring cycle overrun or a silent scheduler, a job waiting over 10 minutes,
 * a failed or overdue backup. Nothing is shown while all is well. */
export function OpsAlerts() {
  const alerts = useQuery({
    queryKey: ["ops", "alerts"],
    queryFn: ({ signal }) => fetchOpsAlerts(signal),
    refetchInterval: 60_000,
  });
  if (!alerts.data?.length) return null;
  return (
    <section className="panel" aria-labelledby="ops-title">
      <h2 id="ops-title" className="panel-title">
        Operational alerts
      </h2>
      <ul className="case-list">
        {alerts.data.map((a, i) => (
          <li key={`${a.kind}-${i}`} className={a.severity === "critical" ? "overdue" : undefined}>
            <strong>{a.severity === "critical" ? "Critical" : "Warning"}:</strong> {a.text}
            {a.link && (
              <>
                {" "}
                <Link to={a.link}>Open</Link>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
