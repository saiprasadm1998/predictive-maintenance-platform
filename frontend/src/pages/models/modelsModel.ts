/** Pure helpers behind model management and version detail (SCR-10, SCR-11). */

import type { LifecycleAction } from "../../api/models";
import type { ModelSummary, VersionSummary } from "../../api/types";

export interface Choice {
  action: LifecycleAction;
  version: VersionSummary;
  label: string;
  consequence: string;
  danger: boolean;
}

/**
 * The lifecycle actions open to a model now (ARC Figure 7), each with the consequence the
 * confirmation states (PDS §6). The server checks them again.
 */
export function lifecycleChoices(model: ModelSummary): Choice[] {
  const out: Choice[] = [];
  const current = model.in_service;
  const latest = model.latest;
  if (latest.status === "Validated" && latest.id !== current?.id) {
    out.push({
      action: "deploy",
      version: latest,
      label: `Deploy v${latest.version}`,
      consequence: current
        ? `v${latest.version} starts scoring at the next cycle and v${current.version} is superseded; its alerts go out of service.`
        : `v${latest.version} starts scoring at the next cycle and raises alerts by its rules.`,
      danger: false,
    });
    out.push({
      action: "reject",
      version: latest,
      label: `Reject v${latest.version}`,
      consequence: `v${latest.version} goes back to Draft, to be changed and trained again.`,
      danger: false,
    });
  }
  if (current?.status === "Deployed") {
    out.push({
      action: "pause",
      version: current,
      label: `Pause v${current.version}`,
      consequence:
        "Scoring stops until resumed; the asset shows Unknown and its alerts go out of service.",
      danger: false,
    });
  }
  if (current?.status === "Paused") {
    out.push({
      action: "resume",
      version: current,
      label: `Resume v${current.version}`,
      consequence: "Scoring restarts at the next cycle and alerts are evaluated again.",
      danger: false,
    });
  }
  if (current) {
    out.push({
      action: "retire",
      version: current,
      label: `Retire v${current.version}`,
      consequence:
        "Scoring stops for good. The asset is no longer monitored by this model; its history is kept.",
      danger: true,
    });
  }
  return out;
}

/** "3.0 / week" from the alerts raised in 30 days. */
export function alertRate(alertsIn30Days: number): string {
  return `${((alertsIn30Days * 7) / 30).toFixed(1)} / week`;
}
