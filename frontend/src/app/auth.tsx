import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useMe } from "./session";

/** Screens need a session; without one, go to sign-in and come back afterwards. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) {
    return (
      <p role="status" className="muted" style={{ padding: 24 }}>
        Loading…
      </p>
    );
  }
  if (me.isError) {
    return (
      <p role="alert" style={{ padding: 24 }}>
        {me.error.message}
      </p>
    );
  }
  if (!me.data) {
    const next = location.pathname + location.search;
    return <Navigate to={`/sign-in?next=${encodeURIComponent(next)}`} replace />;
  }
  return <>{children}</>;
}
