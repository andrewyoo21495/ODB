// Polls a background task until it reaches a terminal state.

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function useTask(taskId: string | null) {
  return useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.getTask(taskId as string),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "error" ? false : 1000;
    },
  });
}
