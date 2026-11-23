import { Link } from "react-router-dom";

import { Badge, PageHeader, Panel } from "../../components/ui";

type Row = [
  code: string,
  what: string,
  who: string,
  release: string,
  screens: [string, string][],
  shows: string,
];

const ROWS: Row[] = [
  [
    "UC-01",
    "Plant data arrives over MQTT and is saved",
    "OT gateway",
    "R1",
    [["Ingestion health", "/system/ingestion"]],
    "Broker state, sources with clock skew and rates, tags with a stale filter, unregistered tags, reject log",
  ],
  [
    "UC-02",
    "Past data is loaded from a CSV or Parquet file",
    "Model engineer",
    "R1",
    [
      ["Historical data", "/setup/history"],
      ["Upload history", "/setup/history/upload"],
    ],
    "Four-step upload: file, column mapping, check, import; coverage per equipment",
  ],
  [
    "UC-03",
    "The plant tree and tag list are set up, by hand or by import",
    "Model engineer, administrator",
    "R1",
    [
      ["Plant hierarchy", "/setup/hierarchy"],
      ["Registry import", "/setup/hierarchy?import=1"],
      ["Equipment types", "/setup/types"],
      ["Equipment register", "/setup/equipment"],
      ["Tags and mapping", "/setup/tags"],
    ],
    "Levels, workbook import with problems by sheet and row, roles with unit, kind and required",
  ],
  [
    "UC-04",
    "Rules that catch bad sensors are set and previewed",
    "Model engineer",
    "R1",
    [
      ["Data-quality rules", "/setup/data-quality"],
      ["Sensor health", "/sensors"],
    ],
    "Inherit, on or off per scope, preview then save; NE 107 categories per sensor",
  ],
  [
    "UC-05",
    "A model is built, trained and tested in the browser",
    "Model engineer",
    "R1",
    [["New model", "/models/new/build/1"]],
    "Six steps: sensors, periods, cleansing, training, validation with the false-alert estimate, limits",
  ],
  [
    "UC-06",
    "A model version is deployed, paused, replaced or retired",
    "Model engineer",
    "R1",
    [["Models", "/models"]],
    "One live version per model, confirmations, re-score a period, limits in force, playback",
  ],
  [
    "UC-07",
    "Models are created for all machines of one type in one go",
    "Model engineer",
    "R2",
    [
      ["Apply a template", "/models?apply=template"],
      ["Equipment types", "/setup/types"],
    ],
    "Pick type and template, check the equipment, preview, create the models",
  ],
  [
    "UC-08",
    "The live fleet health is watched",
    "Reliability engineer, supervisor",
    "R1",
    [
      ["Overview", "/fleet"],
      ["Unit view", "/units"],
      ["Equipment", "/equipment"],
    ],
    "Scope, figures, equipment needing attention, units, recent events",
  ],
  [
    "UC-09",
    "An alert is investigated: trends, contributors, failure-mode match",
    "Reliability engineer",
    "R1–R2",
    [
      ["Equipment analysis", "/assets"],
      ["Alerts", "/alerts"],
    ],
    "Deviation and health, sensors compared, contributors, ranked failure modes with checks",
  ],
  [
    "UC-10",
    "An alert is acknowledged, or shelved with a reason and an end time",
    "Reliability engineer",
    "R1",
    [["Alerts", "/alerts"]],
    "ISA-18.2 states, persistence, shelving up to 7 days with a reason",
  ],
  [
    "UC-11",
    "The time to reach a limit is forecast, with an urgency",
    "Reliability engineer",
    "R2",
    [["Equipment analysis, time to limit", "/assets"]],
    "Load-corrected trend with an interval; already past the limit is Immediate",
  ],
  [
    "UC-12",
    "A case is opened from an alert, assigned and tracked",
    "Reliability, maintenance",
    "R2",
    [["Cases", "/cases"]],
    "Status, priority and overdue; assignee, due date, work order; actions and checks",
  ],
  [
    "UC-13",
    "A case is closed with an outcome and lessons learned",
    "Maintenance, reliability",
    "R2",
    [["Cases", "/cases"]],
    "Outcome required; the confirmed failure mode for a true finding; lessons",
  ],
  [
    "UC-14",
    "A sensor is taken out of the calculation for a set time",
    "Reliability, model engineer",
    "R2",
    [["Sensor health", "/sensors"]],
    "Exclude or override until a date, with a reason; end the exclusion",
  ],
  [
    "UC-15",
    "People receive e-mail about important alerts and cases",
    "Everyone",
    "R2",
    [["Notifications", "/system/notifications"]],
    "Subscriptions by scope and priority, immediate or daily digest, quiet hours, log",
  ],
  [
    "UC-16",
    "Failure modes, symptoms and checks are maintained",
    "Model engineer",
    "R2",
    [["Failure modes", "/library"]],
    "Modes by type, ISO 14224 code, symptoms with weights, checks, versions",
  ],
  [
    "UC-17",
    "Users, roles and machine keys are managed",
    "Administrator",
    "R1",
    [["Users and access", "/system/users"]],
    "Five roles with scope, lockout, ingest and results-read keys shown once",
  ],
  [
    "UC-18",
    "Plant systems read results through the API",
    "Plant systems",
    "R2",
    [["Users and access", "/system/users"]],
    "Health, alerts and forecasts at /api/v1/results with a results-read key; OpenAPI description at /api/v1/docs",
  ],
  [
    "UC-19",
    "Who changed what, and when, is looked up",
    "Administrator",
    "R1",
    [
      ["Audit log", "/system/audit"],
      ["Retention", "/system/retention"],
    ],
    "Filter by date, user and record; before and after; export; retention minimums",
  ],
];

export function CoveragePage() {
  return (
    <>
      <PageHeader
        title="Use-case coverage"
        sub="Use cases UC-01 to UC-19 and the screens that carry them"
      />
      <Panel className="fill">
        <div className="tw">
          <table className="tb">
            <thead>
              <tr>
                <th>Use case</th>
                <th>What happens</th>
                <th>Who</th>
                <th>Release</th>
                <th>Screens</th>
                <th>What the screens show</th>
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([code, what, who, release, screens, shows]) => (
                <tr key={code}>
                  <td className="mono">{code}</td>
                  <td>
                    <b>{what}</b>
                  </td>
                  <td className="sec">{who}</td>
                  <td>
                    <Badge>{release}</Badge>
                  </td>
                  <td>
                    {screens.map(([label, to], i) => (
                      <span key={to}>
                        {i > 0 && ", "}
                        <Link to={to}>{label}</Link>
                      </span>
                    ))}
                  </td>
                  <td className="sec s13">{shows}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}
