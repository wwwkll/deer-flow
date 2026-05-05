import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getBackendBaseURL } from "../config";

export function useNovelTags() {
  return useQuery<{ tags: string[] }>({
    queryKey: ["novel-tags"],
    queryFn: async () => {
      const response = await fetch(`${getBackendBaseURL()}/api/novel-tags/`);
      if (!response.ok) {
        throw new Error("Failed to fetch novel tags");
      }
      return response.json();
    },
    staleTime: 5 * 60 * 1000,
  });
}

export function useRefreshNovelTags() {
  const queryClient = useQueryClient();

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["novel-tags"] });
    const response = await fetch(
      `${getBackendBaseURL()}/api/novel-tags/?refresh=1`,
    );
    if (!response.ok) {
      throw new Error("Failed to refresh novel tags");
    }
    const data = await response.json();
    queryClient.setQueryData(["novel-tags"], data);
    return data as { tags: string[] };
  };

  return { refresh };
}

interface ThreadVariable {
  key: string;
  value: string;
  description: string;
  is_system: boolean;
  llm_editable: boolean;
  updated_at: string;
  updated_by: string;
}

export function useThreadNovelToc(threadId: string, isNewThread: boolean) {
  return useQuery<string | undefined>({
    queryKey: ["thread-novel-toc", threadId],
    enabled: !isNewThread,
    queryFn: async () => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/global-variables/threads/${threadId}`,
      );
      if (!response.ok) {
        return undefined;
      }
      const data = (await response.json()) as {
        variables: ThreadVariable[];
      };
      const novelToc = data.variables.find((v) => v.key === "novel_toc");
      return novelToc?.value ?? null;
    },
    staleTime: 30 * 1000,
  });
}
