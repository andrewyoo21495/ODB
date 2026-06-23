// Per-page data selector bound to the shared JobContext: pick which uploaded
// job a feature page operates on without returning to the dashboard. Changing
// it here updates the global "current job" so other pages pre-fill the same
// choice (hybrid: one default, independently changeable per tab).

import { Select, Space } from "antd";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import type { JobOut } from "../types";

function jobLabel(j: JobOut): string {
  const extra = [j.project, j.model, j.revision ? `rev ${j.revision}` : ""]
    .filter(Boolean)
    .join(" · ");
  return extra ? `${j.original_filename} — ${extra}` : j.original_filename;
}

export default function JobSelect({ width = 460 }: { width?: number }) {
  const { jobId, setJobId } = useJob();
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  return (
    <Space>
      <span style={{ color: "#888" }}>데이터:</span>
      <Select
        showSearch
        style={{ width }}
        placeholder="분석할 데이터 선택"
        loading={jobs.isLoading}
        optionFilterProp="label"
        value={jobId ?? undefined}
        onChange={(v) => setJobId(v)}
        options={(jobs.data ?? []).map((j) => ({
          label: jobLabel(j),
          value: j.job_id,
        }))}
      />
    </Space>
  );
}
