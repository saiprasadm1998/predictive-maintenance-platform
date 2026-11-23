import * as Dialog from "@radix-ui/react-dialog";
import { type ReactNode, useId, useState } from "react";

import { ICONS } from "./icons";
import { Icon } from "./ui";

/**
 * Confirmation for state-changing actions (PDS §5, §6): it states the consequence, and asks
 * for a reason where one is mandatory (shelve, override, retire ...). The confirm button
 * stays disabled until the reason is given; a failure is shown in the dialog.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  consequence,
  confirmLabel,
  danger = false,
  reasonLabel,
  reasonOptional = false,
  children,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  consequence: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  /** When set, a reason field is shown and passed to onConfirm (required unless optional). */
  reasonLabel?: string;
  reasonOptional?: boolean;
  /** Extra fields (an expiry, for example). */
  children?: ReactNode;
  onConfirm: (reason: string) => Promise<void> | void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonId = useId();
  const hasReason = reasonLabel !== undefined;
  const needsReason = hasReason && !reasonOptional;
  const ready = !needsReason || reason.trim().length > 0;

  function change(next: boolean) {
    if (busy) return;
    if (!next) {
      setReason("");
      setError(null);
    }
    onOpenChange(next);
  }

  async function confirm(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
      setReason("");
      onOpenChange(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The action failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={change}>
      <Dialog.Portal>
        <Dialog.Overlay className="scrim">
          <Dialog.Content
            className="dlg"
            style={{ fontFamily: "var(--app-font)", fontSize: 14, lineHeight: 1.5 }}
          >
            <div className="dlgh">
              <Dialog.Title asChild>
                <h2>{title}</h2>
              </Dialog.Title>
              <Dialog.Close className="iconbtn" aria-label="Close" disabled={busy}>
                <Icon d={ICONS.close} size={20} />
              </Dialog.Close>
            </div>
            <form onSubmit={confirm} style={{ display: "contents" }}>
              <div className="dlgb">
                <Dialog.Description asChild>
                  <div>{consequence}</div>
                </Dialog.Description>
                {hasReason && (
                  <div className="fld">
                    <label htmlFor={reasonId}>
                      {reasonLabel} ({needsReason ? "required" : "optional"})
                    </label>
                    <textarea
                      id={reasonId}
                      className="ta"
                      value={reason}
                      required={needsReason}
                      onChange={(event) => setReason(event.target.value)}
                    />
                  </div>
                )}
                {children}
                <div role="alert" className="err">
                  {error}
                </div>
              </div>
              <div className="dlgf">
                <Dialog.Close asChild>
                  <button type="button" className="btn btn-s" disabled={busy}>
                    Cancel
                  </button>
                </Dialog.Close>
                <button
                  type="submit"
                  className={danger ? "btn btn-d" : "btn btn-p"}
                  disabled={!ready || busy}
                >
                  {busy ? "Working…" : confirmLabel}
                </button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
