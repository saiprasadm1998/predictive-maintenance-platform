import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { addExclusion, endExclusion } from "../../api/admin";
import { useAnnounce } from "../../app/liveContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { UNTIL_CHOICES } from "./sensorsModel";

export type ExclusionAction =
  | { kind: "exclude" | "override"; tagId: number; name: string }
  | { kind: "end"; exclusionId: number; name: string; what: "exclude" | "override" };

/**
 * UC-14: exclude a sensor (Function check, out of every model) or override its status to
 * Good, with a reason and an expiry; or end one early. Confirmed with its consequence.
 */
export function ExclusionDialog({
  action,
  onDone,
}: {
  action: ExclusionAction | null;
  onDone: () => void;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [hours, setHours] = useState(24);
  const kind = action?.kind;
  const name = action?.name ?? "";

  async function confirm(reason: string) {
    if (!action) return;
    if (action.kind === "end") {
      await endExclusion(action.exclusionId);
      announce(`${name}: ${action.what === "override" ? "override" : "exclusion"} ended`);
    } else {
      const until = new Date(Date.now() + hours * 3_600_000).toISOString();
      await addExclusion(action.tagId, { kind: action.kind, reason, until });
      announce(`${name} ${action.kind === "override" ? "overridden to Good" : "excluded"}`);
    }
    await client.invalidateQueries({
      predicate: (q) => ["sensors", "models", "scores", "assets"].includes(String(q.queryKey[0])),
    });
  }

  const title =
    kind === "exclude"
      ? `Exclude ${name}`
      : kind === "override"
        ? `Override ${name} to Good`
        : action?.kind === "end"
          ? `End the ${action.what === "override" ? "override" : "exclusion"} of ${name}`
          : "";
  const consequence =
    kind === "exclude"
      ? "From the next cycle the sensor is Function check and left out of every model that uses it; the models predict it from the others. It returns to the normal rules at the expiry."
      : kind === "override"
        ? "From the next cycle its automatic status (out of range, flatline, spike or uncertain quality) is shown as Good and the sensor is used in scoring. Bad quality and missing data are never overridden."
        : "From the next cycle the sensor is judged by the normal rules again.";

  return (
    <ConfirmDialog
      open={action !== null}
      onOpenChange={(open) => !open && onDone()}
      title={title}
      consequence={consequence}
      confirmLabel={kind === "exclude" ? "Exclude" : kind === "override" ? "Override" : "End"}
      danger={kind !== "end"}
      reasonLabel={kind === "end" ? undefined : "Reason"}
      onConfirm={confirm}
    >
      {kind !== "end" && (
        <label className="field">
          <span>Until</span>
          <select
            className="control"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            {UNTIL_CHOICES.map(([h, text]) => (
              <option key={h} value={h}>
                {text}
              </option>
            ))}
          </select>
        </label>
      )}
    </ConfirmDialog>
  );
}
