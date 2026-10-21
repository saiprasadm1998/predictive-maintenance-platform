import { ApiError, api, setCsrfToken } from "./client";

export interface Role {
  role: string;
  scope_asset_id: number | null;
}

export interface User {
  id: number;
  username: string;
  display_name: string;
  email: string | null;
  roles: Role[];
}

interface SessionOut {
  user: User;
  csrf_token: string;
}

/** The signed-in user, or null when there is no session. */
export async function fetchMe(signal?: AbortSignal): Promise<User | null> {
  try {
    const session = await api<SessionOut>("/auth/me", { signal });
    setCsrfToken(session.csrf_token);
    return session.user;
  } catch (error) {
    if (error instanceof ApiError && error.unauthenticated) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

export async function signIn(username: string, password: string): Promise<User> {
  const session = await api<SessionOut>("/auth/login", {
    method: "POST",
    body: { username, password },
  });
  setCsrfToken(session.csrf_token);
  return session.user;
}

export async function signOut(): Promise<void> {
  try {
    await api<void>("/auth/logout", { method: "POST" });
  } finally {
    setCsrfToken(null);
  }
}
