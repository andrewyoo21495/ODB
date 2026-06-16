import { useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Spin,
  Table,
  Tag,
  Upload,
} from "antd";
import { InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useJob } from "../JobContext";
import type { JobOut } from "../types";

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
      />
    </Card>
  );
}
