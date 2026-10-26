import { useCallback, useRef } from "react";

const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]), select, [tabindex='0']";

function focusables(element: Element): HTMLElement[] {
  return [...element.querySelectorAll<HTMLElement>(FOCUSABLE)];
}

/**
 * PDS §5 keyboard use of long tables: on a row's link or button, the up and down arrows move
 * to the same column of the row above or below (or that row's first control), skipping rows
 * with nothing to focus. Lists, text fields and selects keep their own arrow keys.
 */
function moveRowFocus(event: KeyboardEvent): void {
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const target = event.target as HTMLElement;
  if (target.closest("select, textarea, input:not([type='checkbox'])")) return;
  const row = target.closest("tr");
  if (!row) return;
  const column = target.closest<HTMLTableCellElement>("td, th")?.cellIndex ?? 0;
  const step = (r: Element | null) =>
    event.key === "ArrowDown" ? r?.nextElementSibling : r?.previousElementSibling;
  let next = step(row);
  while (next && !focusables(next).length) next = step(next);
  if (!next) return;
  const cell = next.children[column];
  const into = (cell && focusables(cell)[0]) ?? focusables(next)[0];
  if (!into) return;
  event.preventDefault();
  into.focus();
}

/** A ref for a table whose body rows the arrow keys move between (see moveRowFocus). */
export function useRowKeys(): (table: HTMLTableElement | null) => void {
  const current = useRef<HTMLTableElement | null>(null);
  return useCallback((table: HTMLTableElement | null) => {
    current.current?.removeEventListener("keydown", moveRowFocus);
    current.current = table;
    table?.addEventListener("keydown", moveRowFocus);
  }, []);
}
