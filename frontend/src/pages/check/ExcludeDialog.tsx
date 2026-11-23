import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { addExclusion } from "../../api/admin";
import { errorMessages } from "../../api/client";
import { formatDateTime } from "../../app/format";
import { Dialog, Problems } from "../../components/ui";

const UNTIL = [
  [24, "24 hours"],
  [7 * 24, "7 days"],
  [30 * 24, "30 days"],
  [90 * 24, "90 days (maximum)"],
] as const;

/** Exclude a sensor from scoring, or override its automatic status, with a reason and an end. */
export function ExcludeDialog({
  tagId,
  name,
  coverage,
  onClose,
}: {
  tagId: number;
  name: string;
  coverage?: string;
  onClose: () => void;
}) {
  const client = useQueryClient();
  const [kind, setKind] = useState<"exclude" | "override">("exclude");
  const [reason, setReason] = useState("");
  const [hours, setHours] = useState(24);
  const [tried, setTried] = useState(false);
  const [now] = useState(() => Date.now());
  const ends = new Date(now + hours * 3_600_000);
  const save = useMutation({
    mutationFn: () =>
      addExclusion(tagId, { kind, reason: reason.trim(), until: ends.toISOString() }),
    onSuccess: async () => {
      await client.invalidateQueries({
        predicate: (q) => ["sensors", "models", "scores", "assets"].includes(String(q.queryKey[0])),
      });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`${kind === "exclude" ? "Exclude" : "Override"} ${name}`}
      footer={
        <>
          <button className="btn btn-s" type="button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-p"
            type="button"
            disabled={save.isPending}
            onClick={() => {
              setTried(true);
              if (reason.trim()) save.mutate();
            }}
          >
            {kind === "exclude" ? "Exclude" : "Override"}
          </button>
        </>
      }
    >
      <p className="sec s13">
        {kind === "exclude"
          ? "From the next cycle the sensor is Function check and left out of every model that uses it; the models predict it from the others. It returns to the normal rules at the end time."
          : "The sensor's automatic status is set to Good until the end time, so models keep using it. Use this only when you have checked the instrument."}
      </p>
      <div className="fld">
        <label htmlFor="ex-a">Action</label>
        <select
          id="ex-a"
          className="sl"
          value={kind}
          onChange={(e) => setKind(e.target.value as "exclude" | "override")}
        >
          <option value="exclude">Exclude from scoring</option>
          <option value="override">Override the automatic status</option>
        </select>
      </div>
      <div className="fld">
        <label htmlFor="ex-r">Reason (required)</label>
        <textarea
          id="ex-r"
          className="ta"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="For example transmitter replaced, calibration pending"
        />
        {tried && !reason.trim() && <span className="err">Enter a reason.</span>}
      </div>
      <div className="fg">
        <div className="fld">
          <label htmlFor="ex-u">Until</label>
          <select
            id="ex-u"
            className="sl"
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          >
            {UNTIL.map(([h, l]) => (
              <option key={h} value={h}>
                {l}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="ex-e">Ends</label>
          <input id="ex-e" className="in" value={formatDateTime(ends)} disabled />
        </div>
      </div>
      {coverage && kind === "exclude" && <div className="notice">{coverage}</div>}
      <Problems messages={save.isError ? errorMessages(save.error) : []} />
    </Dialog>
  );
}
