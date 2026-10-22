import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

import { AnnounceContext } from "./liveContext";

/** One polite live region for the whole app; repeated messages are announced again. */
export function Announcer({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const timer = useRef<number | undefined>(undefined);
  const announce = useCallback((text: string) => {
    setMessage("");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(text), 50);
  }, []);
  // A message still waiting when the app goes away (sign-out, a test ending) is dropped.
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <div className="visually-hidden" role="status" aria-live="polite" aria-atomic="true">
        {message}
      </div>
    </AnnounceContext.Provider>
  );
}
