import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  InputNumber,
  Progress,
  Space,
  Statistic,
} from "antd";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFeature } from "../hooks/useFeature";
import { useJobName } from "../hooks/useJobName";
import ReportView from "../components/ReportView";

type CopperSummary = { layers: number; avg_ratio: number; report: string };

export default function Copper() {
  const { message } = AntdApp.useApp();
  // VECTOR 방식 고정 사용 (raster 경로는 백엔드에 보존되어 있으나 UI에서는 숨김).
  const method = "vector" as const;
  const [rows, setRows] = useState(5);
  const [cols, setCols] = useState(5);
  const { jobId, taskId, setTaskId, task, prior } = useFeature("copper");
  const jobName = useJobName(jobId);

  const run = useMutation({
    mutationFn: () =>
      api.runCopper(jobId as string, { method, n_rows: rows, n_cols: cols }),
    onSuccess: (t) => setTaskId(t.task_id),
    onError: (e) => message.error(String(e)),
  });

  if (!jobId) {
    return <Alert type="info" showIcon message="대시보드에서 Job을 먼저 선택하세요." />;
  }

  const status = task.data?.status;
  const running = run.isPending || (!!taskId && status !== "done" && status !== "error");
  const done = status === "done";
  const res = task.data?.result as CopperSummary | undefined;
  const priorRes = prior?.summary as CopperSummary | undefined;

  return (
    <Card title={`동박율 계산 — ${jobName || jobId}`}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Space wrap>
          <span>grid:</span>
          <InputNumber min={1} max={50} value={rows} onChange={(v) => setRows(v ?? 5)} />
          <span>×</span>
          <InputNumber min={1} max={50} value={cols} onChange={(v) => setCols(v ?? 5)} />
        </Space>

        <Button type="primary" loading={running} onClick={() => run.mutate()}>
          {prior && !done ? "다시 계산" : "계산 실행"}
        </Button>

        {running && taskId && (
          <Alert
            type="info"
            showIcon
            message="레이어별 copper ratio 계산 중… (레이어 수에 따라 수십 초 소요)"
          />
        )}
        {running && taskId && <Progress percent={Math.round((task.data?.progress ?? 0) * 100)} status="active" />}

        {status === "error" && (
          <Alert type="error" showIcon message={task.data?.error ?? "실행 오류"} />
        )}

        {done && res && (
          <>
            <Space size="large">
              <Statistic title="평균 Copper Ratio" value={(res.avg_ratio * 100).toFixed(1)} suffix="%" />
              <Statistic title="Signal 레이어" value={res.layers} />
            </Space>
            <ReportView src={api.reportUrl(taskId as string)} downloadName={`copper_${jobId}.html`} />
          </>
        )}

        {!done && !running && priorRes && (
          <>
            <Alert
              type="success"
              showIcon
              message={`이전 계산 결과 (${new Date(prior!.completed_at).toLocaleString()})`}
            />
            <Space size="large">
              <Statistic title="평균 Copper Ratio" value={(priorRes.avg_ratio * 100).toFixed(1)} suffix="%" />
              <Statistic title="Signal 레이어" value={priorRes.layers} />
            </Space>
            <ReportView src={api.reportByKindUrl(jobId, "copper")} downloadName={`copper_${jobId}.html`} />
          </>
        )}
      </Space>
    </Card>
  );
}
