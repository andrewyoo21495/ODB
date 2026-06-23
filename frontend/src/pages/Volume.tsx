import { Alert, App as AntdApp, Button, Card, Col, Row, Space, Statistic } from "antd";
import { useMutation } from "@tanstack/react-query";
import { api } from "../api/client";
import { useFeature } from "../hooks/useFeature";
import JobSelect from "../components/JobSelect";
import ReportView from "../components/ReportView";

interface SideResult {
  count: number;
  total_volume_mm3: number;
  missing_height: number;
}

type VolumeSummary = {
  report: string;
  grand_total_mm3: number;
  top: SideResult;
  bottom: SideResult;
};

function SideStats({ title, side }: { title: string; side: SideResult }) {
  return (
    <Card size="small" title={title}>
      <Space size="large" wrap>
        <Statistic title="총 부피" value={side.total_volume_mm3.toFixed(2)} suffix="mm³" />
        <Statistic title="부품 수" value={side.count} />
        <Statistic title="높이 미상" value={side.missing_height} />
      </Space>
    </Card>
  );
}

function VolumeResults({ res }: { res: VolumeSummary }) {
  return (
    <>
      <Card size="small">
        <Statistic
          title="전체 부피 (TOP + BOTTOM)"
          value={res.grand_total_mm3.toFixed(2)}
          suffix="mm³"
          valueStyle={{ fontWeight: 700 }}
        />
      </Card>
      <Row gutter={16}>
        <Col xs={24} md={12}>
          <SideStats title="TOP" side={res.top} />
        </Col>
        <Col xs={24} md={12}>
          <SideStats title="BOTTOM" side={res.bottom} />
        </Col>
      </Row>
    </>
  );
}

export default function Volume() {
  const { message } = AntdApp.useApp();
  const { jobId, taskId, setTaskId, task, prior } = useFeature("volume");

  const run = useMutation({
    mutationFn: () => api.runVolume(jobId as string),
    onSuccess: (t) => setTaskId(t.task_id),
    onError: (e) => message.error(String(e)),
  });

  const status = task.data?.status;
  const running = run.isPending || (!!taskId && status !== "done" && status !== "error");
  const done = status === "done";
  const res = task.data?.result as VolumeSummary | undefined;
  const priorRes = prior?.summary as VolumeSummary | undefined;

  return (
    <Card title="PCB 부품 부피 계산">
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <JobSelect />
        {!jobId ? (
          <Alert type="info" showIcon message="분석할 데이터를 선택하세요." />
        ) : (
          <Space direction="vertical" style={{ width: "100%" }} size="middle">
            <Button type="primary" loading={running} onClick={() => run.mutate()}>
              {prior && !done ? "다시 분석" : "분석 실행"}
            </Button>

            {running && taskId && (
              <Alert type="info" showIcon message="부품 부피 계산 중…" />
            )}
            {status === "error" && (
              <Alert type="error" showIcon message={task.data?.error ?? "실행 오류"} />
            )}

            {done && res && (
              <>
                <VolumeResults res={res} />
                <ReportView src={api.reportUrl(taskId as string)} downloadName={`volume_${jobId}.html`} />
              </>
            )}

            {!done && !running && priorRes && (
              <>
                <Alert
                  type="success"
                  showIcon
                  message={`이전 분석 결과 (${new Date(prior!.completed_at).toLocaleString()})`}
                />
                <VolumeResults res={priorRes} />
                <ReportView src={api.reportByKindUrl(jobId, "volume")} downloadName={`volume_${jobId}.html`} />
              </>
            )}
          </Space>
        )}
      </Space>
    </Card>
  );
}
