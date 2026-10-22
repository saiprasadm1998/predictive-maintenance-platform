import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchAllAssets } from "../../api/assets";
import { type Unmapped, fetchUnmapped } from "../../api/registry";
import { formatDateTime } from "../../app/format";
import { Skeleton } from "../fleet/FleetPage";
import { emptyTag } from "./registryModel";
import { TagForm } from "./TagsTab";

/** FR-ING-06: names the gateways send that are not registered; register one to keep its data. */
export function UnmappedTab({ editable }: { editable: boolean }) {
  const unmapped = useQuery({
    queryKey: ["unmapped"],
    queryFn: ({ signal }) => fetchUnmapped(signal),
  });
  const assets = useQuery({
    queryKey: ["assets", "all"],
    queryFn: ({ signal }) => fetchAllAssets(signal),
  });
  const [promoting, setPromoting] = useState<Unmapped | null>(null);
  if (unmapped.isPending) return <Skeleton rows={4} />;
  if (unmapped.isError)
    return <p role="alert">The unmapped tags could not be loaded: {unmapped.error.message}</p>;

  return (
    <div className="registry-split">
      <section className="panel" aria-labelledby="unmapped-title">
        <h2 id="unmapped-title" className="panel-title">
          Unmapped tags ({unmapped.data.length})
        </h2>
        {unmapped.data.length === 0 ? (
          <p className="muted">Every name the gateways send is registered.</p>
        ) : (
          <table className="tree-table">
            <caption className="visually-hidden">Names received that are not registered</caption>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Source name</th>
                <th scope="col">First seen</th>
                <th scope="col">Last seen</th>
                <th scope="col" className="num">
                  Samples
                </th>
                {editable && <th scope="col">Register</th>}
              </tr>
            </thead>
            <tbody>
              {unmapped.data.map((u) => (
                <tr key={`${u.source}/${u.source_name}`}>
                  <td>{u.source}</td>
                  <td className="mono">{u.source_name}</td>
                  <td>{formatDateTime(new Date(u.first_seen))}</td>
                  <td>{formatDateTime(new Date(u.last_seen))}</td>
                  <td className="num">{u.count.toLocaleString("en-GB")}</td>
                  {editable && (
                    <td>
                      <button
                        type="button"
                        className="button button-small"
                        aria-label={`Register ${u.source_name}`}
                        onClick={() => setPromoting(u)}
                      >
                        Register…
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {promoting && (
        <TagForm
          key={`${promoting.source}/${promoting.source_name}`}
          tag={null}
          promote
          initial={emptyTag(promoting.source, promoting.source_name)}
          assets={(assets.data ?? []).filter((a) => a.level === "equipment")}
          onDone={() => setPromoting(null)}
        />
      )}
    </div>
  );
}
