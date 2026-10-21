import {
  type Band,
  type Ne107,
  type Severity,
  type StatusLook,
  bandLook,
  ne107Look,
  severityLook,
} from "./status";
import { StatusShape } from "./StatusShape";

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

/** Shape + label + colour for a band, severity or NE 107 status (PDS §3.2, §5). */
export function StatusChip(props: Props) {
  const look = lookOf(props);
  const size = props.size ?? "m";
  const separator = props.kind === "ne107" && props.value === "Failure" ? ": " : " — ";
  return (
    <span
      className={`chip chip-${size} tone-${look.tone}${props.bold === false ? " chip-regular" : ""}`}
      data-status={props.value}
    >
      <StatusShape shape={look.shape} tone={look.tone} size={size === "s" ? 10 : 12} />
      <span className="chip-label">
        {look.label}
        {props.detail ? (
          <span className="chip-detail">
            {separator}
            {props.detail}
          </span>
        ) : null}
      </span>
    </span>
  );
}
