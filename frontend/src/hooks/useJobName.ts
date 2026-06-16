// Resolve the display name (original filename) for the current job so feature
// page titles show the file the user uploaded instead of the opaque job hash.

import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function useJobName(jobId: string | null): string {
  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId as string),
    enabled: !!jobId,
  });
  return job.data?.original_filename || job.data?.job_name || "";
}
