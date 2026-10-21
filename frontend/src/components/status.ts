/**
 * Status encoding (PDS §3.2): every status has a shape, a text label and a colour, so the
 * interface works in greyscale and for colour-vision deficiency (WCAG 1.4.1). This table is
 * the only place the three are paired; components draw from it.
 */

export type Shape =
  | "triangle" // filled ▲
  | "diamond" // filled ◆
  | "circle" // hollow ○
  | "dashed-square" // dashed ▢
  | "square" // filled ■
  | "hollow-square"; // hollow □

export type Tone = "alert" | "watch" | "healthy" | "unknown" | "fault";

export interface StatusLook {
  shape: Shape;
  tone: Tone;
  label: string;
}

/** Health band of an asset or model (ARC §4: Healthy, Watch, Alert, Unknown). */
export type Band = "Alert" | "Watch" | "Healthy" | "Unknown";
export const BANDS: readonly Band[] = ["Alert", "Watch", "Unknown", "Healthy"];

/** Severity of an alert. */
export type Severity = "Alert" | "Warning";
export const SEVERITIES: readonly Severity[] = ["Alert", "Warning"];

/** NE 107 sensor status (UCS §6.1). */
export type Ne107 =
  "Good" | "Failure" | "Out of specification" | "Maintenance required" | "Function check";
export const NE107: readonly Ne107[] = [
  "Good",
  "Failure",
  "Out of specification",
  "Maintenance required",
  "Function check",
];

const BAND_LOOK: Record<Band, StatusLook> = {
  Alert: { shape: "triangle", tone: "alert", label: "ALERT" },
  Watch: { shape: "diamond", tone: "watch", label: "WATCH" },
  Healthy: { shape: "circle", tone: "healthy", label: "Healthy" },
  Unknown: { shape: "dashed-square", tone: "unknown", label: "Unknown" },
};

const SEVERITY_LOOK: Record<Severity, StatusLook> = {
  Alert: { shape: "triangle", tone: "alert", label: "ALERT" },
  Warning: { shape: "diamond", tone: "watch", label: "WARNING" },
};

const NE107_LOOK: Record<Ne107, StatusLook> = {
  Good: { shape: "circle", tone: "healthy", label: "Good" },
  Failure: { shape: "square", tone: "fault", label: "Failure" },
  "Out of specification": { shape: "diamond", tone: "watch", label: "Out of specification" },
  "Maintenance required": { shape: "diamond", tone: "watch", label: "Maintenance required" },
  "Function check": { shape: "hollow-square", tone: "unknown", label: "Function check" },
};

export function bandLook(band: Band): StatusLook {
  return BAND_LOOK[band];
}

export function severityLook(severity: Severity): StatusLook {
  return SEVERITY_LOOK[severity];
}

export function ne107Look(status: Ne107): StatusLook {
  return NE107_LOOK[status];
}

/** Alert states (ISA-18.2, UCS Figure 6). */
export type AlertState =
  | "Normal"
  | "Active-Unacknowledged"
  | "Active-Acknowledged"
  | "RTN-Unacknowledged"
  | "Shelved"
  | "Out of service";

export const ALERT_STATES: readonly AlertState[] = [
  "Active-Unacknowledged",
  "Active-Acknowledged",
  "RTN-Unacknowledged",
  "Shelved",
  "Out of service",
  "Normal",
];

/** True when the alert still needs someone to acknowledge it (ISA-18.2). */
export function needsAck(state: AlertState): boolean {
  return state === "Active-Unacknowledged" || state === "RTN-Unacknowledged";
}
