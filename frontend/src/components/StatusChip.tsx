import {
  type Band,
  type Ne107,
  type Severity,
  type StatusLook,
  bandLook,
  ne107Look,
  severityLook,
} from "./status";

type Props = (
  | { kind: "band"; value: Band }
  | { kind: "severity"; value: Severity }
  | { kind: "ne107"; value: Ne107 }
) & {
  /** Why (Unknown: the reason; Failure: the rule), shown after the label. */
  detail?: string | null;
  size?: "s" | "m";
  bold?: boolean;
};

function lookOf(props: Props): StatusLook {
  switch (props.kind) {
    case "band":
      return bandLook(props.value);
    case "severity":
      return severityLook(props.value);
    case "ne107":
      return ne107Look(props.value);
  }
}

const PILL: Record<string, string> = {
  alert: " p-danger",
  fault: " p-danger",
  watch: " p-warning",
  unknown: " p-unknown",
  healthy: "",
};

function sentence(label: string): string {
  return label === label.toUpperCase() ? label.charAt(0) + label.slice(1).toLowerCase() : label;
}

/** A band, severity or NE 107 status as a Traverse pill: dot, label, tone (never colour alone). */
export function StatusChip(props: Props) {
  const look = lookOf(props);
  const separator = props.kind === "ne107" && props.value === "Failure" ? ": " : " — ";
  return (
    <span className={`pill${PILL[look.tone] ?? ""}`} data-status={props.value}>
      <span className="d" />
      <span>
        {sentence(look.label)}
        {props.detail ? (
          <span className="sec">
            {separator}
            {props.detail}
          </span>
        ) : null}
      </span>
    </span>
  );
}
