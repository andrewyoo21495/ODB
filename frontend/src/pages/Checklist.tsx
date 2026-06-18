import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Progress,
  Select,
  Space,
} from "antd";
import { ReadOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFeature } from "../hooks/useFeature";
import JobSelect from "../components/JobSelect";
import ReportView from "../components/ReportView";

export default function Checklist() {
  const { message } = AntdApp.useApp();
  const [selected, setSelected] = useState<string[]>([]);
  const { jobId, taskId, setTaskId, task, prior } = useFeature("checklist");

  const rules = useQuery({ queryKey: ["rules"], queryFn: api.getRules });

  const run = useMutation({
    mutationFn: () => api.runChecklist(jobId as string, selected.length ? selected : null),
    onSuccess: (t) => setTaskId(t.task_id),
    onError: (e) => message.error(String(e)),
  });

  const status = task.data?.status;
  const running = run.isPending || (!!taskId && status !== "done" && status !== "error");
  const done = status === "done";

  return (
    <Card
      title="체크리스트"
      extra={
        <Button
          icon={<ReadOutlined />}
          href="/api/docs/checklist"
          target="_blank"
          rel="noopener"
        >
          검토기준
        </Button>
      }
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <JobSelect />
        {!jobId ? (
          <Alert type="info" showIcon message="분석할 데이터를 선택하세요." />
        ) : (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <Space.Compact style={{ width: "100%" }}>
              <Button style={{ cursor: "default" }} disabled>
                체크리스트 항목 선택:
              </Button>
              <Select
                mode="multiple"
                allowClear
                style={{ flex: 1 }}
                placeholder="검토하려는 항목 선택. 비우면 전체 검토 실행"
                loading={rules.isLoading}
                value={selected}
                onChange={setSelected}
                options={(rules.data ?? []).map((r) => ({
                  label: `${r.rule_id} — ${r.description}`,
                  value: r.rule_id,
                }))}
              />
              <Button type="primary" loading={running} onClick={() => run.mutate()}>
                {prior && !done ? "다시 실행" : "실행"}
              </Button>
            </Space.Compact>

            {running && taskId && (
              <Progress
                percent={Math.round((task.data?.progress ?? 0) * 100)}
                status="active"
              />
            )}

            {status === "error" && (
              <Alert type="error" showIcon message={task.data?.error ?? "실행 오류"} />
            )}

            {done ? (
              <ReportView src={api.reportUrl(taskId as string)} downloadName={`checklist_${jobId}.html`} />
            ) : (
              !running && prior && (
                <>
                  <Alert
                    type="success"
                    showIcon
                    message={`이전 검토 결과 (${new Date(prior.completed_at).toLocaleString()})`}
                  />
                  <ReportView src={api.reportByKindUrl(jobId, "checklist")} downloadName={`checklist_${jobId}.html`} />
                </>
              )
            )}
          </Space>
        )}
      </Space>
    </Card>
  );
}
