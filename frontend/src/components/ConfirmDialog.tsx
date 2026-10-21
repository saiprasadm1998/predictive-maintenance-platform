import * as Dialog from "@radix-ui/react-dialog";
import { type ReactNode, useId, useState } from "react";

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
  children,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  consequence: ReactNode;
  confirmLabel: string;
  danger?: boolean;
  /** When set, a reason is required and passed to onConfirm. */
  reasonLabel?: string;
  /** Extra fields (an expiry, for example). */
  children?: ReactNode;
  onConfirm: (reason: string) => Promise<void> | void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reasonId = useId();
  const needsReason = reasonLabel !== undefined;
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
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog">
          <form onSubmit={confirm} style={{ display: "grid", gap: 12 }}>
            <Dialog.Title className="dialog-title">{title}</Dialog.Title>
            <Dialog.Description asChild>
              <div>{consequence}</div>
            </Dialog.Description>
            {needsReason && (
              <label className="field" htmlFor={reasonId}>
                <span>{reasonLabel} (required)</span>
                <textarea
                  id={reasonId}
                  className="control"
                  value={reason}
                  required
                  onChange={(event) => setReason(event.target.value)}
                />
              </label>
            )}
            {children}
            <div role="alert" className="form-error">
              {error}
            </div>
            <div className="dialog-actions">
              <Dialog.Close asChild>
                <button type="button" className="button" disabled={busy}>
                  Cancel
                </button>
              </Dialog.Close>
              <button
                type="submit"
                className={danger ? "button button-danger" : "button button-primary"}
                disabled={!ready || busy}
              >
                {busy ? "Working…" : confirmLabel}
              </button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
