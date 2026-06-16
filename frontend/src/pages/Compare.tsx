import { useState } from "react";
import { Alert, App as AntdApp, Button, Card, List, Select, Space, Tag } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useTask } from "../hooks/useTask";
import ReportView from "../components/ReportView";
import type { JobOut } from "../types";

export default function Compare() {
  const { message } = AntdApp.useApp();
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const [oldId, setOldId] = useState<string | null>(null);
  const [newId, setNewId] = useState<string | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const task = useTask(taskId);

  const run = useMutation({
    mutationFn: () => api.runCompare(oldId as string, newId as string),
    onSuccess: (t) => setTaskId(t.task_id),
    onError: (e) => message.error(String(e)),
  });

  const options = (jobs.data ?? []).map((j: JobOut) => ({
    label: `${j.original_filename} (${j.job_id})`,
    value: j.job_id,
  }));

  const status = task.data?.status;
  const running = run.isPending || (!!taskId && status !== "done" && status !== "error");
  const done = status === "done";
  const res = task.data?.result as
    | { report: string; summaries: { comparator_id: string; title: string; summary: string }[] }
    | undefined;

  return (
    <Card title="Revision Comparator">
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Space wrap>
          <span>OLD:</span>
          <Select
            style={{ width: 360 }}
            placeholder="이전 리비전 Job"
            loading={jobs.isLoading}
            value={oldId}
            onChange={setOldId}
            options={options}
          />
          <span>NEW:</span>
          <Select
            style={{ width: 360 }}
            placeholder="새 리비전 Job"
            loading={jobs.isLoading}
            value={newId}
            onChange={setNewId}
            options={options}
          />
        </Space>

        <Button
          type="primary"
          disabled={!oldId || !newId}
          loading={running}
          onClick={() => run.mutate()}
        >
          비교 실행
        </Button>

        {running && taskId && <Alert type="info" showIcon message="리비전 비교 중…" />}
        {status === "error" && (
          <Alert type="error" showIcon message={task.data?.error ?? "실행 오류"} />
        )}

        {done && res && (
          <>
            <List
              size="small"
              bordered
              dataSource={res.summaries}
              renderItem={(s) => (
                <List.Item>
                  <Tag color="blue">{s.comparator_id}</Tag>
                  <b style={{ marginRight: 8 }}>{s.title}</b>
                  <span>{s.summary}</span>
                </List.Item>
              )}
            />
            <ReportView src={api.reportUrl(taskId as string)} />
          </>
        )}
      </Space>
    </Card>
  );
}
