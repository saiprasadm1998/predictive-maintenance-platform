import { QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "../api/client";

export const ME_KEY = ["auth", "me"] as const;

/** A client error (4xx) will not change on retry; server and network errors may. */
function shouldRetry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failures < 2;
}

export function createQueryClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      // Any read answered 401 means the session ended (idle timeout, sign-out elsewhere):
      // forget the user, and the route guard sends them to sign-in.
      onError: (error) => {
        if (error instanceof ApiError && error.unauthenticated) client.setQueryData(ME_KEY, null);
      },
    }),
    defaultOptions: {
      queries: { retry: shouldRetry, staleTime: 30_000, refetchOnWindowFocus: true },
      mutations: { retry: false },
    },
  });
  return client;
}
