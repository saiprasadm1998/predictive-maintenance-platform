import { useEffect, useRef } from "react";
import { useBlocker } from "react-router-dom";

import { ConfirmDialog } from "./ConfirmDialog";

/**
 * PDS §6: leaving a form with unsaved changes asks first, both for a link inside the app
 * (another screen or tab) and for closing or reloading the browser tab.
 */
export function UnsavedChanges({ dirty }: { dirty: boolean }) {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      dirty &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search),
  );
  const leaving = useRef(false);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  return (
    <ConfirmDialog
      open={blocker.state === "blocked"}
      onOpenChange={(open) => {
        if (open) return;
        if (!leaving.current && blocker.state === "blocked") blocker.reset();
        leaving.current = false;
      }}
      title="Leave without saving?"
      consequence="Your changes to this form have not been saved and will be lost."
      confirmLabel="Leave"
      danger
      onConfirm={() => {
        leaving.current = true;
        if (blocker.state === "blocked") blocker.proceed();
      }}
    />
  );
}
