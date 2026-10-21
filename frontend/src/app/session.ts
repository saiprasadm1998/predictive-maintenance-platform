import { useQuery, useQueryClient } from "@tanstack/react-query";

import { type User, fetchMe, signIn, signOut } from "../api/auth";
import { ME_KEY } from "./queryClient";

export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: ({ signal }) => fetchMe(signal),
    staleTime: Infinity,
  });
}

export function useSignIn() {
  const client = useQueryClient();
  return async (username: string, password: string): Promise<User> => {
    const user = await signIn(username, password);
    client.clear();
    client.setQueryData(ME_KEY, user);
    return user;
  };
}

export function useSignOut() {
  const client = useQueryClient();
  return async (): Promise<void> => {
    try {
      await signOut();
    } finally {
      client.clear();
      client.setQueryData(ME_KEY, null);
    }
  };
}
