import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useDashboard(window: string) {
  return useQuery({
    queryKey: ["dashboard", window],
    queryFn: () => api.getDashboard(window),
    refetchInterval: 5_000, // live-updating dashboard
  });
}
