import type { ReactNode } from "react";

import { errorMessages } from "../../api/client";

/** A form's problems and a failed request's messages, announced (PDS §6). */
export function Problems({ problems, error }: { problems?: string[]; error?: unknown }) {
  const shown = [...(problems ?? []), ...errorMessages(error)];
  if (!shown.length) return null;
  return (
    <ul role="alert" className="form-error builder-problems">
      {shown.map((p) => (
        <li key={p}>{p}</li>
      ))}
    </ul>
  );
}

export function Field({
  label,
  children,
  wide = false,
}: {
  label: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <label className={`field${wide ? " builder-wide" : ""}`}>
      <span>{label}</span>
      {children}
    </label>
  );
}
