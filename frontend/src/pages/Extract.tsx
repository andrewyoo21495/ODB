import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Select,
  Space,
  Statistic,
  Tag,
} from "antd";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFeature } from "../hooks/useFeature";
import ReportView from "../components/ReportView";

type ExtractSummary = {
  count: number;
  by_category: Record<string, number>;
  report: string;
  json: string;
};

const CATEGORIES = [
  "IC",
  "Capacitor",
  "Inductor",
  "Connector",
  "SIM_Socket",
  "INP",
  "Unknown",
];

export default function Extract() {
  const { message } = AntdApp.useApp();
  const [categories, setCategories] = useState<string[]>([]);
  const { jobId, taskId, setTaskId, task, prior } = useFeature("extract");

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
    <Card title={`JSON Extractor — job ${jobId}`}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Select
          mode="multiple"
          allowClear
          style={{ width: "100%" }}
          placeholder="카테고리 선택 (비우면 전체)"
          value={categories}
          onChange={setCategories}
          options={CATEGORIES.map((c) => ({ label: c, value: c }))}
        />

        <Button type="primary" loading={running} onClick={() => run.mutate()}>
          {prior && !done ? "다시 추출" : "추출 실행"}
        </Button>

        {running && taskId && (
          <Alert type="info" showIcon message="부품 필터링 & 이미지 렌더링 중…" />
        )}

        {status === "error" && (
          <Alert type="error" showIcon message={task.data?.error ?? "실행 오류"} />
        )}

        {done && res && (
          <>
            <Space size="large" wrap>
              <Statistic title="추출된 부품" value={res.count} />
              {Object.entries(res.by_category).map(([cat, n]) => (
                <Tag key={cat} color="blue">{`${cat}: ${n}`}</Tag>
              ))}
            </Space>
            <Button href={api.artifactUrl(taskId as string, res.json)} target="_blank">
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
            <Space size="large" wrap>
              <Statistic title="추출된 부품" value={priorRes.count} />
              {Object.entries(priorRes.by_category).map(([cat, n]) => (
                <Tag key={cat} color="blue">{`${cat}: ${n}`}</Tag>
              ))}
            </Space>
            <Button href={api.jobArtifactUrl(jobId, priorRes.json)} target="_blank">
              parts.json 다운로드
            </Button>
            <ReportView src={api.reportByKindUrl(jobId, "extract")} downloadName={`extract_${jobId}.html`} />
          </>
        )}
      </Space>
    </Card>
  );
}
