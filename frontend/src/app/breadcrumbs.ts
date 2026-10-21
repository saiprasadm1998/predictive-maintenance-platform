import { createContext, useContext, useEffect } from "react";

/** One step of the hierarchy shown in the top bar (PDS §2.2). */
export interface BreadcrumbItem {
  label: string;
  to?: string; // absent: the current page
}

export const BreadcrumbContext = createContext<(items: BreadcrumbItem[] | null) => void>(
  () => undefined,
);

/** A screen states where it is in the hierarchy; the top bar shows it. */
export function useBreadcrumbs(items: BreadcrumbItem[] | null): void {
  const set = useContext(BreadcrumbContext);
  const key = JSON.stringify(items);
  useEffect(() => {
    set(items);
    return () => set(null);
    // the items are compared by value
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [set, key]);
}
