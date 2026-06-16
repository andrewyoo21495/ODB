// Per-feature page state: tracks the current task, re-attaches to a task that
// is still running after navigating away, and exposes any prior recorded
// result so returning to a tab shows the previous run instead of a blank page.

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import { useTask } from "./useTask";
import type { ResultOut } from "../types";

export function useFeature(kind: string) {
  const { jobId } = useJob();
  const qc = useQueryClient();
  const [taskId, setTaskId] = useState<string | null>(null);
  const task = useTask(taskId);

  // Prior recorded results for this job (persisted on disk).
  const results = useQuery({
    queryKey: ["results", jobId],
    queryFn: () => api.getResults(jobId as string),
    enabled: !!jobId,
  });

  // On entering the page (no active task yet), re-attach to a still-running task.
  useEffect(() => {
    if (!jobId || taskId) return;
    let cancelled = false;
    api.getLatestTask(jobId, kind).then((t) => {
      if (!cancelled && t && (t.status === "running" || t.status === "queued")) {
        setTaskId(t.task_id);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [jobId, kind, taskId]);

  // When a run finishes, refresh the prior-results list.
  const status = task.data?.status;
  useEffect(() => {
    if (status === "done") qc.invalidateQueries({ queryKey: ["results", jobId] });
  }, [status, jobId, qc]);

  const prior: ResultOut | null =
    (results.data ?? []).find((r) => r.kind === kind) ?? null;

  return { jobId, taskId, setTaskId, task, prior };
}
