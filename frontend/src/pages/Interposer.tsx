import { Alert, App as AntdApp, Button, Card, Col, Row, Space, Statistic } from "antd";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFeature } from "../hooks/useFeature";
import { useJobName } from "../hooks/useJobName";
import ReportView from "../components/ReportView";

interface SideResult {
  pcb_area: number;
  interposer_area: number;
  ratio: number;
  count: number;
}

type InterposerSummary = { report: string; top: SideResult; bottom: SideResult };

function SideStats({ title, side }: { title: string; side: SideResult }) {
  return (
    <Card size="small" title={title}>
      <Space size="large" wrap>
        <Statistic title="비율" value={(side.ratio * 100).toFixed(2)} suffix="%" />
        <Statistic title="Interposer 면적" value={side.interposer_area.toFixed(2)} suffix="mm²" />
        <Statistic title="PCB 면적" value={side.pcb_area.toFixed(2)} suffix="mm²" />
        <Statistic title="개수" value={side.count} />
      </Space>
    </Card>
  );
}

export default function Interposer() {
  const { message } = AntdApp.useApp();
  const { jobId, taskId, setTaskId, task, prior } = useFeature("interposer");
  const jobName = useJobName(jobId);

  const run = useMutation({
    mutationFn: () => api.runInterposer(jobId as string),
    onSuccess: (t) => setTaskId(t.task_id),
    onError: (e) => message.error(String(e)),
  });

  if (!jobId) {
    return <Alert type="info" showIcon message="대시보드에서 Job을 먼저 선택하세요." />;
  }

  const status = task.data?.status;
  const running = run.isPending || (!!taskId && status !== "done" && status !== "error");
  const done = status === "done";
  const res = task.data?.result as InterposerSummary | undefined;
  const priorRes = prior?.summary as InterposerSummary | undefined;

  return (
    <Card title={`인터포저 영역 계산 — ${jobName || jobId}`}>
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <Button type="primary" loading={running} onClick={() => run.mutate()}>
          {prior && !done ? "다시 분석" : "분석 실행"}
        </Button>

        {running && taskId && (
          <Alert type="info" showIcon message="Interposer 면적 분석 중…" />
        )}
        {status === "error" && (
          <Alert type="error" showIcon message={task.data?.error ?? "실행 오류"} />
        )}

        {done && res && (
          <>
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <SideStats title="TOP" side={res.top} />
              </Col>
              <Col xs={24} md={12}>
                <SideStats title="BOTTOM" side={res.bottom} />
              </Col>
            </Row>
            <ReportView src={api.reportUrl(taskId as string)} downloadName={`interposer_${jobId}.html`} />
          </>
        )}

        {!done && !running && priorRes && (
          <>
            <Alert
              type="success"
              showIcon
              message={`이전 분석 결과 (${new Date(prior!.completed_at).toLocaleString()})`}
            />
            <Row gutter={16}>
              <Col xs={24} md={12}>
                <SideStats title="TOP" side={priorRes.top} />
              </Col>
              <Col xs={24} md={12}>
                <SideStats title="BOTTOM" side={priorRes.bottom} />
              </Col>
            </Row>
            <ReportView src={api.reportByKindUrl(jobId, "interposer")} downloadName={`interposer_${jobId}.html`} />
          </>
        )}
      </Space>
    </Card>
  );
}
