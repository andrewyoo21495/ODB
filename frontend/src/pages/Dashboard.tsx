import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Empty,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
} from "antd";
import { DeleteOutlined, DownloadOutlined, InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import { useUser } from "../UserContext";
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
  const { jobId: currentJobId, setJobId } = useJob();
  const { user } = useUser();
  const { message } = AntdApp.useApp();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [scope, setScope] = useState<"mine" | "all">("all");

  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  // Poll a freshly-uploaded job until its cache is built, then refresh the list.
  const pending = useQuery({
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
    refetchInterval: 1000,
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

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteJob(id),
    onSuccess: (_d, id) => {
      message.success("삭제되었습니다");
      if (currentJobId === id) setJobId(null);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) => message.error(String(e)),
  });

  const columns = [
    { title: "파일", dataIndex: "original_filename" },
    { title: "Job", dataIndex: "job_name" },
    { title: "단위", dataIndex: "units", render: (u: string) => <Tag>{u}</Tag> },
    { title: "ODB", dataIndex: "odb_version" },
    {
      title: "업로더",
      dataIndex: "uploaded_by",
      render: (u: string) => <Tag color={u && u === user ? "blue" : "default"}>{u || "anonymous"}</Tag>,
    },
    { title: "업로드", dataIndex: "uploaded_at" },
    {
      title: "",
      key: "action",
      render: (_: unknown, r: JobOut) => (
        <Space>
          <Button
            type="link"
            onClick={() => {
              setJobId(r.job_id);
              nav("/checklist");
            }}
          >
            열기 →
          </Button>
          <Popconfirm
            title="이 데이터를 삭제할까요?"
            description="소스/캐시/리포트가 모두 삭제됩니다."
            okText="삭제"
            okButtonProps={{ danger: true, loading: remove.isPending }}
            cancelText="취소"
            onConfirm={() => remove.mutate(r.job_id)}
          >
            <Button type="text" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
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
        <div style={{ marginTop: 16 }}>
          <Alert
            type="info"
            showIcon
            icon={<Spin size="small" />}
            message={`캐시 빌드 중… (job ${pendingId})`}
            description={pending.data?.message || undefined}
          />
          <Progress
            percent={Math.round((pending.data?.progress ?? 0) * 100)}
            status="active"
            style={{ marginTop: 8 }}
          />
        </div>
      )}

      <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
        <Segmented
          value={scope}
          onChange={(v) => setScope(v as "mine" | "all")}
          options={[
            { label: "내 작업", value: "mine" },
            { label: "전체", value: "all" },
          ]}
          disabled={!user}
        />
      </div>

      <Table
        style={{ marginTop: 8 }}
        rowKey="job_id"
        size="small"
        loading={jobs.isLoading}
        dataSource={(jobs.data ?? []).filter(
          (j) => scope === "all" || !user || j.uploaded_by === user,
        )}
        columns={columns}
        expandable={{
          expandedRowRender: (r: JobOut) => <JobResults jobId={r.job_id} />,
          rowExpandable: () => true,
        }}
      />
    </Card>
  );
}
