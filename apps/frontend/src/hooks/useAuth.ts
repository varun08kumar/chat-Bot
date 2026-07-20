import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

// Access tokens are 3 minutes (see chat-service Settings.access_token_ttl_s).
// Refresh at a fraction of that so a slow network hop never lets the
// token actually expire before the next refresh lands.
const REFRESH_INTERVAL_MS = 2 * 60 * 1000;

export function useSession() {
  return useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: false,
    staleTime: Infinity,
  });
}

export function useAuth() {
  const qc = useQueryClient();
  const { data: user, isLoading, isError } = useSession();

  // Silent background refresh — as long as the tab is open, the session
  // keeps renewing itself without the user ever seeing a 3-minute logout.
  useEffect(() => {
    if (!user) return;
    const id = setInterval(() => {
      api.refresh().catch(() => {
        // Refresh token itself expired/invalid — let the next /auth/me
        // check (or the next API 401) surface the logged-out state
        // naturally rather than forcing it here.
        qc.invalidateQueries({ queryKey: ["me"] });
      });
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, [user, qc]);

  const login = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => api.login(email, password),
    onSuccess: (u) => qc.setQueryData(["me"], u),
  });

  const register = useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) => api.register(email, password),
    onSuccess: (u) => qc.setQueryData(["me"], u),
  });

  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => {
      qc.setQueryData(["me"], null);
      qc.clear();
    },
  });

  return {
    user: user ?? null,
    isLoading,
    isAuthenticated: !isError && !!user,
    login,
    register,
    logout,
  };
}
