import { Link, useSearchParams } from "react-router-dom";

import { useBreadcrumbs } from "../../app/breadcrumbs";
import { useMe } from "../../app/session";
import { HierarchyTab } from "./HierarchyTab";
import { HistoryTab } from "./HistoryTab";
import { ImportTab } from "./ImportTab";
import { canEditRegistry } from "./registryModel";
import { TagsTab } from "./TagsTab";
import { TypesTab } from "./TypesTab";
import { UnmappedTab } from "./UnmappedTab";

const TABS = [
  { key: "hierarchy", label: "Hierarchy" },
  { key: "tags", label: "Tags" },
  { key: "types", label: "Asset types and roles" },
  { key: "import", label: "Registry import" },
  { key: "history", label: "History import" },
  { key: "unmapped", label: "Unmapped tags" },
] as const;

/**
 * SCR-13 Registry and import (PDS §4, UC-02, UC-03, FR-REG-01 to -04, FR-ING-06): the asset
 * hierarchy, tags, asset types with their roles, imports with a validation report, history
 * import with a preview, and the tags the gateways send that are not registered yet.
 * Everyone may look; Model Engineers and Administrators change (ARC §9.2).
 */
export function RegistryPage() {
  useBreadcrumbs([{ label: "Administration", to: "/admin" }, { label: "Registry and import" }]);
  const [params] = useSearchParams();
  const me = useMe();
  const tab = TABS.find((t) => t.key === params.get("tab"))?.key ?? "hierarchy";
  const editable = canEditRegistry(me.data);

  return (
    <div className="registry">
      <nav aria-label="Registry sections">
        <ul className="tabs">
          {TABS.map((t) => (
            <li key={t.key}>
              <Link
                to={`/admin/registry?tab=${t.key}`}
                aria-current={t.key === tab ? "page" : undefined}
                className={t.key === tab ? "tab tab-on" : "tab"}
              >
                {t.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      {!editable && (
        <p className="muted small">
          You can look at the registry; Model Engineers and Administrators change it.
        </p>
      )}
      {tab === "hierarchy" ? (
        <HierarchyTab editable={editable} />
      ) : tab === "tags" ? (
        <TagsTab editable={editable} />
      ) : tab === "types" ? (
        <TypesTab editable={editable} />
      ) : tab === "import" ? (
        <ImportTab editable={editable} />
      ) : tab === "history" ? (
        <HistoryTab editable={editable} />
      ) : (
        <UnmappedTab editable={editable} />
      )}
    </div>
  );
}
