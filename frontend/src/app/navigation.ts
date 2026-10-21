/** Only a path inside this app may follow sign-in (never another site). */
export function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/fleet";
  }
  return next;
}
