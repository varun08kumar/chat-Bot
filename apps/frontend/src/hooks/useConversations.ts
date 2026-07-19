import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

export function useConversations(search?: string) {
  return useQuery({
    queryKey: ["conversations", search ?? ""],
    queryFn: () => api.listConversations(search),
  });
}

export function useConversation(id: string | null) {
  return useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api.getConversation(id as string),
    enabled: !!id,
  });
}

export function useDeleteConversation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteConversation(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["conversations"] }),
  });
}

export function useProviders() {
  return useQuery({ queryKey: ["providers"], queryFn: () => api.getProviders(), staleTime: 60_000 });
}
