import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";

export function useAgentFavorites() {
  return useQuery<string[]>({
    queryKey: ["agent-favorites"],
    queryFn: async () => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/agent-favorites`,
      );
      if (!response.ok) throw new Error("Failed to fetch favorites");
      const data = (await response.json()) as { favorites: string[] };
      return data.favorites;
    },
  });
}

export function useAddFavorite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (agentName: string) => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/agent-favorites/${encodeURIComponent(agentName)}`,
        { method: "PUT" },
      );
      if (!response.ok) throw new Error("Failed to add favorite");
      return response.json() as Promise<{
        success: boolean;
        agent_name: string;
      }>;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-favorites"] });
    },
  });
}

export function useRemoveFavorite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (agentName: string) => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/agent-favorites/${encodeURIComponent(agentName)}`,
        { method: "DELETE" },
      );
      if (!response.ok) throw new Error("Failed to remove favorite");
      return response.json() as Promise<{
        success: boolean;
        agent_name: string;
      }>;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["agent-favorites"] });
    },
  });
}
