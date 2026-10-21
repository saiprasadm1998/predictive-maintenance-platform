import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { changeVersion } from "../../api/models";
import type { ModelSummary } from "../../api/types";
import { useAnnounce } from "../../app/liveContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { type Choice, lifecycleChoices } from "./modelsModel";

/** Deploy, pause, resume, retire and reject, each confirmed with its consequence. */
export function LifecycleActions({
  model,
  compact = false,
}: {
  model: ModelSummary;
  compact?: boolean;
}) {
  const client = useQueryClient();
  const announce = useAnnounce();
  const [choice, setChoice] = useState<Choice | null>(null);
  const change = useMutation({
    mutationFn: (c: Choice) => changeVersion(c.version.id, c.action),
    onSuccess: (_, c) => {
      announce(`${model.asset_code} / ${model.name}: ${c.label} done`);
      void client.invalidateQueries({
        predicate: (q) =>
          ["models", "assets", "fleet", "alerts", "scores"].includes(String(q.queryKey[0])),
      });
    },
  });
  const choices = lifecycleChoices(model);
  if (!choices.length) return compact ? <span className="muted">—</span> : null;
  return (
    <span className="lifecycle">
      {choices.map((c) => (
        <button
          key={c.action}
          type="button"
          className={`button${compact ? " button-small" : ""}${c.danger ? " button-danger-outline" : ""}`}
          onClick={() => setChoice(c)}
        >
          {c.label}
        </button>
      ))}
      <ConfirmDialog
        open={choice !== null}
        onOpenChange={(open) => !open && setChoice(null)}
        title={choice ? `${choice.label} of ${model.asset_code} / ${model.name}?` : ""}
        consequence={choice?.consequence ?? ""}
        confirmLabel={choice?.label ?? ""}
        danger={choice?.danger}
        onConfirm={async () => {
          if (choice) await change.mutateAsync(choice);
        }}
      />
    </span>
  );
}
