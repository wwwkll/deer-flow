import { useMutation, useQueryClient } from "@tanstack/react-query";

import { getBackendBaseURL } from "@/core/config";

export function useClearCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (categoryName: string) => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/categories/${encodeURIComponent(categoryName)}/clear`,
        { method: "POST" },
      );
      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Failed to clear category" }));
        throw new Error(error.detail ?? "Failed to clear category");
      }
      return response.json() as Promise<{
        success: boolean;
        message: string;
        deleted_count: number;
      }>;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });
}

export function useDeleteCategory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (categoryName: string) => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/categories/${encodeURIComponent(categoryName)}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        const error = await response
          .json()
          .catch(() => ({ detail: "Failed to delete category" }));
        throw new Error(error.detail ?? "Failed to delete category");
      }
      return response.json() as Promise<{
        success: boolean;
        message: string;
        deleted_threads: number;
        novel_path: string | null;
      }>;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["threads", "search"] });
    },
  });
}
