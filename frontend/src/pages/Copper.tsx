import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  InputNumber,
  Progress,
  Segmented,
  Space,
  Statistic,
} from "antd";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import { useTask } from "../hooks/useTask";
import ReportView from "../components/ReportView";

export default function Copper() {
  const { jobId } = useJob();
  const { message } = AntdApp.useApp();
  const [method, setMethod] = useState<"vector" | "raster">("vector");
  const [rows, setRows] = useState(5);
  const [cols, setCols] = useState(5);
  const [taskId, setTaskId] = useState<string | null>(null);

  const task = useTask(taskId);

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
  const res = task.data?.result as
    | { layers: number; avg_ratio: number; report: string }
    | undefined;

  return (
    <Card title={`Copper Calculator — job ${jobId}`}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Space wrap>
          <span>계산 방식:</span>
          <Segmented
            options={[
              { label: "vector", value: "vector" },
              { label: "raster", value: "raster" },
            ]}
            value={method}
            onChange={(v) => setMethod(v as "vector" | "raster")}
          />
          <span>grid:</span>
          <InputNumber min={1} max={50} value={rows} onChange={(v) => setRows(v ?? 5)} />
          <span>×</span>
          <InputNumber min={1} max={50} value={cols} onChange={(v) => setCols(v ?? 5)} />
        </Space>

        <Button type="primary" loading={running} onClick={() => run.mutate()}>
          계산 실행
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
            <ReportView src={api.reportUrl(taskId as string)} />
          </>
        )}
      </Space>
    </Card>
  );
}
