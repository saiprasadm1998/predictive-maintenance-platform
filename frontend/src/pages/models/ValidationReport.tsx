import type { ValidationReport } from "./builderModel";

const pct = (share: number) => `${(share * 100).toFixed(1)} %`;

/**
 * FR-MOD-06, UCS §6.4: what the validation period showed and the limits it suggests, in the
 * wizard after training and on the version page later.
 */
export function ValidationReportTable({ report }: { report: ValidationReport }) {
  const p = report.di_percentiles;
  const sensors = Object.entries(report.sensors ?? {}).sort((a, b) => b[1].nrmse - a[1].nrmse);
  return (
    <>
      <table className="summary-table">
        <caption>Validation report</caption>
        <tbody>
          <tr>
            <th scope="row">Cycles scored</th>
            <td className="num">{report.cycles.toLocaleString("en-GB")}</td>
          </tr>
          <tr>
            <th scope="row">Deviation Index</th>
            <td>
              P50 {p.P50.toFixed(1)} · P95 {p.P95.toFixed(1)} · P99 {p.P99.toFixed(1)} · P99.9{" "}
              {p["P99.9"].toFixed(1)} %
            </td>
          </tr>
          <tr>
            <th scope="row">Outside the model&apos;s envelope</th>
            <td>
              {report.outside_envelope === null
                ? "Not measured by this algorithm"
                : `${pct(report.outside_envelope)} of cycles`}
            </td>
          </tr>
          <tr>
            <th scope="row">Proposed limits</th>
            <td>
              DI warning {report.proposed.di_warning} %, alert {report.proposed.di_alert} %; sensor
              |z| {report.proposed.sensor_warning} and {report.proposed.sensor_alert}
            </td>
          </tr>
          <tr>
            <th scope="row">Estimated false alerts</th>
            <td>
              {report.alerts_per_week.toLocaleString("en-GB")} per week ({report.alerts} in the
              validation period, with the proposed warning)
            </td>
          </tr>
        </tbody>
      </table>
      {report.warning && (
        <p className="form-warning" role="status">
          ⚠ {report.warning}
        </p>
      )}
      {sensors.length > 0 && (
        <details>
          <summary>Each sensor on the validation period ({sensors.length})</summary>
          <table className="tree-table">
            <caption className="visually-hidden">Prediction error per sensor</caption>
            <thead>
              <tr>
                <th scope="col">Sensor</th>
                <th scope="col" className="num">
                  Normalised RMSE
                </th>
                <th scope="col" className="num">
                  Bias
                </th>
              </tr>
            </thead>
            <tbody>
              {sensors.map(([name, s]) => (
                <tr key={name}>
                  <td className="mono">{name}</td>
                  <td className="num">{pct(s.nrmse)}</td>
                  <td className="num">{s.bias.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </>
  );
}
