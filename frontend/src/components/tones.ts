import type { Band } from "./status";
import type { ToneName } from "./ui";

export function bandTone(band: Band | null | undefined): ToneName {
  switch (band) {
    case "Alert":
      return "danger";
    case "Watch":
      return "warning";
    case "Healthy":
      return "neutral";
    default:
      return "unknown";
  }
}
