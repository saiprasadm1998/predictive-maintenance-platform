import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { type ImportReport, importRegistry } from "../../api/registry";
import { useAnnounce } from "../../app/liveContext";
import { Problems } from "./common";
import { countText } from "./registryModel";

const SHEETS = ["asset_types", "roles", "assets", "tags"];

/**
 * UC-03: import the registry from CSV files or one workbook. The files are validated first
 * (nothing is changed) and the report lists every problem by sheet, line and column; only
 * a clean validation can be imported, all or nothing.
 */
export function ImportTab({ editable }: { editable: boolean }) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const inputId = useId();
  const [files, setFiles] = useState<File[]>([]);
  const [report, setReport] = useState<ImportReport | null>(null);
  const run = useMutation({
    mutationFn: (dryRun: boolean) => importRegistry(files, dryRun),
    onSuccess: (result) => {
      setReport(result);
      if (result.committed) {
        announce("Registry imported");
        void client.invalidateQueries({
          predicate: (q) =>
            ["assets", "tags", "asset-types", "fleet", "unmapped"].includes(String(q.queryKey[0])),
        });
      } else {
        announce(
          result.problems.length
            ? `${result.problems.length} problems found; nothing was changed`
            : "The files are valid",
        );
      }
    },
  });

  if (!editable)
    return <p className="muted">Model Engineers and Administrators import the registry.</p>;
  const valid = report && report.dry_run && !report.problems.length;

  return (
    <section className="panel" aria-labelledby="import-title">
      <h2 id="import-title" className="panel-title">
        Registry import
      </h2>
      <p className="muted small">
        CSV files named after their sheet (<code>asset_types.csv</code>, <code>roles.csv</code>,{" "}
        <code>assets.csv</code>, <code>tags.csv</code>), or one Excel workbook with those sheets.
        Existing rows are updated by code; nothing is deleted.
      </p>
      <div className="builder-row">
        <label className="field" htmlFor={inputId}>
          <span>Files</span>
          <input
            id={inputId}
            className="control"
            type="file"
            multiple
            accept=".csv,.xlsx"
            onChange={(e) => {
              setFiles([...(e.target.files ?? [])]);
              setReport(null);
            }}
          />
        </label>
        <span className="lifecycle">
          <button
            type="button"
            className="button"
            disabled={!files.length || run.isPending}
            onClick={() => run.mutate(true)}
          >
            Validate
          </button>
          <button
            type="button"
            className="button button-primary"
            disabled={!valid || run.isPending}
            onClick={() => run.mutate(false)}
          >
            Import
          </button>
        </span>
      </div>
      <Problems error={run.error} />
      {report && <ReportView report={report} />}
    </section>
  );
}

function ReportView({ report }: { report: ImportReport }) {
  const sheets = [
    ...SHEETS.filter((s) => s in report.counts),
    ...Object.keys(report.counts).filter((s) => !SHEETS.includes(s)),
  ];
  return (
    <div className="registry-report">
      <p role="status">
        <strong>
          {report.problems.length
            ? `Rejected: ${report.problems.length} problem${report.problems.length === 1 ? "" : "s"}. Nothing was changed.`
            : report.committed
              ? "Imported."
              : "Valid. Nothing has been changed yet: Import applies it."}
        </strong>
      </p>
      {report.problems.length > 0 ? (
        <table className="tree-table">
          <caption>Validation report</caption>
          <thead>
            <tr>
              <th scope="col">Sheet</th>
              <th scope="col" className="num">
                Line
              </th>
              <th scope="col">Column</th>
              <th scope="col">Problem</th>
            </tr>
          </thead>
          <tbody>
            {report.problems.map((p, i) => (
              <tr key={i}>
                <td>{p.sheet}</td>
                <td className="num">{p.line || "—"}</td>
                <td className="mono">{p.column || "—"}</td>
                <td>{p.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <table className="summary-table">
          <caption>{report.committed ? "Changes made" : "Changes the import will make"}</caption>
          <tbody>
            {sheets.map((s) => (
              <tr key={s}>
                <th scope="row">{s}</th>
                <td>{countText(report.counts[s] ?? {})}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
