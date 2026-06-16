import { useState } from "react";
import { Alert, App as AntdApp, Button, Card, Select, Space } from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFeature } from "../hooks/useFeature";
import { useJobName } from "../hooks/useJobName";
import ReportView from "../components/ReportView";

type ExtractSummary = {
  count: number;
  by_category: Record<string, number>;
  report: string;
  json: string;
};

// Only the categories component_classifier confidently identifies — "Unknown"
// is intentionally excluded (it is never an extractable category).
const CATEGORIES = [
  "IC",
  "Capacitor",
  "Inductor",
  "Connector",
  "SIM_Socket",
  "INP",
];

export default function Extract() {
  const { message } = AntdApp.useApp();
  const [categories, setCategories] = useState<string[]>([]);
  const { jobId, taskId, setTaskId, task, prior } = useFeature("extract");
  const jobName = useJobName(jobId);

  const run = useMutation({
    mutationFn: () =>
      api.runExtract(jobId as string, categories.length ? categories : null),
    onSuccess: (t) => setTaskId(t.task_id),
    onError: (e) => message.error(String(e)),
  });

  if (!jobId) {
    return <Alert type="info" showIcon message="대시보드에서 Job을 먼저 선택하세요." />;
  }

  const status = task.data?.status;
  const running = run.isPending || (!!taskId && status !== "done" && status !== "error");
  const done = status === "done";
  const res = task.data?.result as ExtractSummary | undefined;
  const priorRes = prior?.summary as ExtractSummary | undefined;

  return (
    <Card title={`데이터 추출 — ${jobName || jobId}`}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Space.Compact style={{ width: "100%" }}>
          <Button style={{ cursor: "default" }} disabled>
            카테고리 선택:
          </Button>
          <Select
            mode="multiple"
            allowClear
            style={{ flex: 1 }}
            placeholder="추출할 부품 카테고리 선택. 비우면 전체 추출"
            value={categories}
            onChange={setCategories}
            options={CATEGORIES.map((c) => ({ label: c, value: c }))}
          />
          <Button type="primary" loading={running} onClick={() => run.mutate()}>
            {prior && !done ? "다시 추출" : "추출 실행"}
          </Button>
        </Space.Compact>

        {running && taskId && (
          <Alert type="info" showIcon message="부품 필터링 & 이미지 렌더링 중…" />
        )}

        {status === "error" && (
          <Alert type="error" showIcon message={task.data?.error ?? "실행 오류"} />
        )}

        {done && res && (
          <>
            <Button
              icon={<DownloadOutlined />}
              href={api.artifactUrl(taskId as string, res.json)}
              target="_blank"
            >
              parts.json 다운로드
            </Button>
            <ReportView src={api.reportUrl(taskId as string)} downloadName={`extract_${jobId}.html`} />
          </>
        )}

        {!done && !running && priorRes && (
          <>
            <Alert
              type="success"
              showIcon
              message={`이전 추출 결과 (${new Date(prior!.completed_at).toLocaleString()})`}
            />
            <Button
              icon={<DownloadOutlined />}
              href={api.jobArtifactUrl(jobId, priorRes.json)}
              target="_blank"
            >
              parts.json 다운로드
            </Button>
            <ReportView src={api.reportByKindUrl(jobId, "extract")} downloadName={`extract_${jobId}.html`} />
          </>
        )}
      </Space>
    </Card>
  );
}
