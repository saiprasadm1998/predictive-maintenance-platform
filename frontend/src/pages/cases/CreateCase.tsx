import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { createCase } from "../../api/cases";
import type { Alert } from "../../api/types";
import { useMe } from "../../app/session";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { canCreateCases, caseBlocker } from "./caseModel";

/**
 * "Create case…" (UC-12 step 1) from the alert list, asset analysis or diagnostics: the
 * chosen alerts of one asset become a case with a snapshot of what is known now, and the
 * case opens. Shown to analysts and model engineers only (ARC §9.2).
 */
export function CreateCaseButton({
  alerts,
  label = "Create case…",
}: {
  alerts: Alert[];
  label?: string;
}) {
  const me = useMe();
  const client = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  if (!canCreateCases(me.data)) return null;
  const blocker = caseBlocker(alerts);
  const count = alerts.length;
  return (
    <>
      <button
        type="button"
        className="button"
        disabled={blocker !== null}
        title={blocker ?? undefined}
        onClick={() => setOpen(true)}
      >
        {label}
      </button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Create a case from ${count} alert${count === 1 ? "" : "s"}`}
        consequence={
          <>
            The case takes the highest alert priority and keeps a snapshot of the DI trend,
            contributors, failure-mode matches, forecast and data quality as they are now. Its
            alerts cannot join another open case.
          </>
        }
        confirmLabel="Create case"
        reasonLabel="Title"
        reasonOptional
        onConfirm={async (title) => {
          const made = await createCase(
            alerts.map((a) => a.id),
            title || null,
          );
          void client.invalidateQueries({
            predicate: (q) => ["alerts", "fleet", "cases"].includes(String(q.queryKey[0])),
          });
          void navigate(`/cases/${made.id}`);
        }}
      />
    </>
  );
}
