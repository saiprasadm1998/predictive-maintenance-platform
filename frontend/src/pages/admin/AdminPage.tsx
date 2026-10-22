import { Link, useSearchParams } from "react-router-dom";

import { useBreadcrumbs } from "../../app/breadcrumbs";
import { useMe } from "../../app/session";
import { AuditTab } from "./AuditTab";
import { isAdministrator } from "./adminModel";
import { KeysTab } from "./KeysTab";
import { RetentionTab } from "./RetentionTab";
import { RulesTab } from "./RulesTab";
import { UsersTab } from "./UsersTab";

const TABS = [
  { key: "users", label: "Users and roles", admin: true },
  { key: "keys", label: "API keys", admin: true },
  { key: "rules", label: "Data-quality rules", admin: false },
  { key: "retention", label: "Retention", admin: true },
  { key: "audit", label: "Audit log", admin: true },
] as const;

/**
 * SCR-14 Administration (PDS §4; UC-17, UC-19, UC-04, FR-SEC, FR-AUD-01): users and roles,
 * API keys, data-quality rules, data retention and the audit log. The registry has its own
 * screen (SCR-13). Administrators manage users, keys, retention and the audit log; Model
 * Engineers change the data-quality rules (ARC §9.2).
 */
export function AdminPage() {
  useBreadcrumbs([{ label: "Administration" }]);
  const [params] = useSearchParams();
  const me = useMe();
  const admin = isAdministrator(me.data);
  const tabs = TABS.filter((t) => admin || !t.admin);
  const tab = tabs.find((t) => t.key === params.get("tab"))?.key ?? tabs[0]!.key;

  return (
    <div className="registry">
      <nav aria-label="Administration sections">
        <ul className="tabs">
          {tabs.map((t) => (
            <li key={t.key}>
              <Link
                to={`/admin?tab=${t.key}`}
                aria-current={t.key === tab ? "page" : undefined}
                className={t.key === tab ? "tab tab-on" : "tab"}
              >
                {t.label}
              </Link>
            </li>
          ))}
          <li>
            <Link to="/admin/registry" className="tab">
              Registry and import
            </Link>
          </li>
        </ul>
      </nav>
      {!admin && (
        <p className="muted small">
          Users, API keys, retention and the audit log are managed by Administrators.
        </p>
      )}
      {tab === "users" ? (
        <UsersTab />
      ) : tab === "keys" ? (
        <KeysTab />
      ) : tab === "rules" ? (
        <RulesTab />
      ) : tab === "retention" ? (
        <RetentionTab />
      ) : (
        <AuditTab />
      )}
    </div>
  );
}
