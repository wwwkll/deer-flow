"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { getBackendBaseURL } from "../config";

async function fetchRunningThreadIds(): Promise<string[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/running-status`,
  );
  if (!response.ok) {
    throw new Error("Failed to fetch running status");
  }
  const data = (await response.json()) as { running_thread_ids: string[] };
  return data.running_thread_ids ?? [];
}

export function useRunningThreads() {
  const query = useQuery<string[]>({
    queryKey: ["threads", "running-status"],
    queryFn: fetchRunningThreadIds,
    refetchInterval: (query) => {
      if (query.state.error) return false;
      const data = query.state.data;
      return data && data.length > 0 ? 10_000 : false;
    },
    refetchOnWindowFocus: true,
  });

  const runningSet = new Set(query.data ?? []);

  return {
    runningThreadIds: runningSet,
    isRunning: (threadId: string) => runningSet.has(threadId),
    hasAnyRunning: runningSet.size > 0,
  };
}

export function useStartRunningPolling() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({
      queryKey: ["threads", "running-status"],
    });
  };
}
