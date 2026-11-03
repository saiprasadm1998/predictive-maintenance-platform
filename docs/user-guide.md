# PMP user guide

A short guide to the Predictive Maintenance Platform for the people who use it every day.
Open PMP in a browser at the address your administrator gives you and sign in with your
user name and password. What you can do depends on your role (section 7).

## 1. The idea in one paragraph

Each monitored asset has a model that learnt its normal behaviour. Every minute PMP
compares the sensors with what the model expects. The difference becomes the **Deviation
Index (DI)**, 0 % when the asset behaves normally, and a **Health** score from 100 down
to 0. The **band** sums it up: **Healthy**, **Watch** (DI past the warning limit),
**Alert** (past the alert limit) or **Unknown** (the model cannot judge, for example
because data is missing or the machine is stopped). Bands always come with a word and a
shape, never colour alone.

## 2. Finding what needs attention

- **Fleet overview** opens first: the asset hierarchy with each asset's band and Health,
  the figures for the fleet (alerts by priority, open cases, sensors with bad data) and
  **Highest deviation now**. Click an asset to open it, or a figure to filter.
- The **time range** (top bar: 1 h to 90 d, or your own dates) applies to every screen and
  stays in the link, so a link you send shows the same period.
- A "No new scores" banner means some models have not been scored for three cycles: their
  figures may be old. Tell your administrator.

## 3. Looking at an asset (Asset analysis)

- The **DI** and **Health** trends with the warning and alert limits; grey stretches are
  periods the model could not score (stopped, out of its operating mode, missing data).
- **Top contributors now:** the sensors that drive the deviation. Click a point on the DI
  trend to see the contributors at that time.
- The **sensor table:** each sensor's value, prediction, deviation and data quality.
  **Chart** adds its trend (actual against predicted); shaded parts are times it was not
  used. Each chart has **View data** to read it as a table.
- **Diagnose** ranks likely failure modes by how well the symptoms match, with the
  recommended tasks, and shows the **forecast**: how long until the DI or a sensor reaches
  its limit, with an urgency (Immediate, High, Medium, Low).

## 4. Alerts (Alert list)

- An alert is raised when the DI or a sensor stays past its limit long enough. Its
  **priority** (P1 highest to P4) comes from the asset's criticality and the severity.
- **Acknowledge** to say you have seen it (with a comment). **Shelve** to silence it for a
  set time with a reason, for example during known work; it comes back when the time ends.
- Filter by priority, state, severity, asset, forecast urgency or whether it has a case, and
  sort by urgency, persistence or case as well as age and priority; you can save filters.
- An alert returns to normal by itself when the condition clears; an unacknowledged one
  stays in the list until acknowledged.

## 5. Cases: from alert to closed work

1. **Create case…** from the alert list, the asset or diagnostics. The case keeps a
   snapshot of the evidence (trend, contributors, diagnosis, forecast) as it was.
2. Assign it, set the priority and due date, add the likely failure mode.
3. Add **actions** (inspect, replace, adjust), or **Add tasks of …** to copy a likely
   failure mode's recommended tasks; record what was found and done; attach photos or
   reports.
4. **Close** with the outcome: **True finding**, **False alert**, **Sensor issue** or
   **Known condition**. A false alert asks the model engineers to review the model. Add
   lessons learnt if useful.

Maintenance users see and work on the cases assigned to them.

## 6. E-mail notifications

**My notifications** (in the user menu): choose which events e-mail you (alert raised,
escalated to Alert, case assigned to you, case overdue), the minimum priority, and a part
of the hierarchy. PMP sends at most one e-mail per alert every 30 minutes and 20 an hour;
the rest come together in one summary. Shelved alerts are not e-mailed.

## 7. Roles

| Role | Can |
| ---- | --- |
| Viewer | See everything in their part of the hierarchy |
| Reliability analyst | Also acknowledge and shelve alerts, run forecasts, create and work on cases |
| Maintenance | See everything; work on cases assigned to them |
| Model engineer | Also build, deploy, pause and retire models, set alert limits, data-quality rules and the failure-mode library |
| Administrator | Users and roles, API keys, retention, ingestion health, notifications and the audit log; they do not work on cases |

## 8. For model engineers

- **Model management** lists every model with its version in service, status and alert
  rate. **Apply template…** creates models for many assets of one type at once.
- The **Model builder** has six steps: 1 Asset and sensors, 2 Training and validation
  periods, 3 Cleanse data, 4 Train and validate, 5 Alert limits, 6 Deploy. Drafts save
  themselves; training runs in the background and the validation report proposes limits.
- On a **Model version** page: its definition, validation results, what it scored, its
  history, and **Re-score…** to compute a past period again (no alerts, no e-mails).
- **Sensor health** shows each sensor's data-quality status (NE 107: Good, Failure, Out of
  specification, Maintenance required, Function check) and the rule behind it. Excluding
  a sensor puts it in Function check, out of every model, until the end you set.
  Data-quality rules are under Administration.

## 9. Help

Something looks wrong (an asset stuck on Unknown, an alert that should not be there, a
sensor reading nonsense): note the asset, the time and what you expected, and tell your
model engineer or administrator.
