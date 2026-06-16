import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Empty,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
} from "antd";
import { DownloadOutlined, InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import type { JobOut } from "../types";

const KIND_LABEL: Record<string, string> = {
  extract: "데이터 추출",
  checklist: "체크리스트",
  copper: "동박율 계산",
  interposer: "인터포저 영역 계산",
  compare: "리비전 비교",
};

// Completed analyses for one job — view / download prior reports without re-running.
function JobResults({ jobId }: { jobId: string }) {
  const results = useQuery({
    queryKey: ["results", jobId],
    queryFn: () => api.getResults(jobId),
  });
  if (results.isLoading) return <Spin size="small" />;
  const items = results.data ?? [];
  if (!items.length) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="완료된 작업 없음" />;
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {items.map((r) => (
        <Space key={r.kind} wrap>
          <Tag color="green">{KIND_LABEL[r.kind] ?? r.kind}</Tag>
          <span style={{ color: "#888", fontSize: 12 }}>
            {new Date(r.completed_at).toLocaleString()}
          </span>
          {r.report && (
            <>
              <Button size="small" href={api.reportByKindUrl(jobId, r.kind)} target="_blank">
                결과 보기
              </Button>
              <Button
                size="small"
                icon={<DownloadOutlined />}
                href={`${api.reportByKindUrl(jobId, r.kind)}?download=1`}
                download
              >
                다운로드
              </Button>
            </>
          )}
        </Space>
      ))}
    </Space>
  );
}

export default function Dashboard() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { setJobId } = useJob();
  const { message } = AntdApp.useApp();
  const [pendingId, setPendingId] = useState<string | null>(null);

  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  // Poll a freshly-uploaded job until its cache is built, then refresh the list.
  useQuery({
    queryKey: ["jobStatus", pendingId],
    queryFn: async () => {
      const s = await api.jobStatus(pendingId as string);
      if (s.status === "ready") {
        setPendingId(null);
        qc.invalidateQueries({ queryKey: ["jobs"] });
      } else if (s.status === "error") {
        setPendingId(null);
        message.error(`캐시 빌드 실패: ${s.error ?? ""}`);
      }
      return s;
    },
    enabled: !!pendingId,
    refetchInterval: 1500,
  });

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadJob(file),
    onSuccess: (s) => {
      message.success(`업로드: ${s.job_id} (${s.status})`);
      if (s.status === "ready") {
        qc.invalidateQueries({ queryKey: ["jobs"] });
      } else {
        setPendingId(s.job_id);
      }
    },
    onError: (e) => message.error(String(e)),
  });

  const columns = [
    { title: "파일", dataIndex: "original_filename" },
    { title: "Job", dataIndex: "job_name" },
    { title: "단위", dataIndex: "units", render: (u: string) => <Tag>{u}</Tag> },
    { title: "ODB", dataIndex: "odb_version" },
    { title: "업로드", dataIndex: "uploaded_at" },
    {
      title: "",
      key: "action",
      render: (_: unknown, r: JobOut) => (
        <Button
          type="link"
          onClick={() => {
            setJobId(r.job_id);
            nav("/checklist");
          }}
        >
          열기 →
        </Button>
      ),
    },
  ];

  return (
    <Card title="대시보드 — ODB++ 업로드 & Job">
      <Upload.Dragger
        accept=".tgz"
        showUploadList={false}
        multiple={false}
        customRequest={({ file, onSuccess }) => {
          upload.mutate(file as File);
          onSuccess?.({});
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">ODB++ .tgz 파일을 드래그하거나 클릭하여 업로드</p>
      </Upload.Dragger>

      {pendingId && (
        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          icon={<Spin size="small" />}
          message={`캐시 빌드 중… (job ${pendingId})`}
        />
      )}

      <Table
        style={{ marginTop: 16 }}
        rowKey="job_id"
        size="small"
        loading={jobs.isLoading}
        dataSource={jobs.data ?? []}
        columns={columns}
        expandable={{
          expandedRowRender: (r: JobOut) => <JobResults jobId={r.job_id} />,
          rowExpandable: () => true,
        }}
      />
    </Card>
  );
}
