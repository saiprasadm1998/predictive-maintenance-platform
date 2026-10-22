import { Link } from "react-router-dom";

import { useBreadcrumbs } from "../../app/breadcrumbs";

/** SCR-14 Administration: its sections. Users, keys, data quality, retention and the audit
 * log arrive in 6.6b; the registry is its own screen (SCR-13). */
export function AdminPage() {
  useBreadcrumbs([{ label: "Administration" }]);
  return (
    <section className="panel" aria-labelledby="admin-title">
      <h2 id="admin-title" className="panel-title">
        Administration
      </h2>
      <ul className="admin-links">
        <li>
          <Link to="/admin/registry">Registry and import</Link>
          <span className="muted"> · hierarchy, tags, asset types, imports, unmapped tags</span>
        </li>
      </ul>
      <p className="muted small">
        Users and roles, API keys, data-quality rules, retention and the audit log arrive next.
      </p>
    </section>
  );
}
