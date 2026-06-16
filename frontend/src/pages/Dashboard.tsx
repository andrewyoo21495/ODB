import { useEffect, useMemo, useState } from "react";
import {
  App as AntdApp,
  Button,
  Card,
  Empty,
  Popconfirm,
  Segmented,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
} from "antd";
import { DeleteOutlined, DownloadOutlined, EditOutlined, InboxOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import JobMetaModal from "../components/JobMetaModal";
import { useJob } from "../JobContext";
import { useUser } from "../UserContext";
import type { JobMeta, JobOut } from "../types";

// A table row is a fetched job, optionally an in-progress upload placeholder
// (_pending) carrying its live build progress (0–1).
type JobRow = JobOut & { _pending?: boolean; _progress?: number };

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
  const [scope, setScope] = useState<"mine" | "all">("all");
  // File awaiting metadata entry before upload; job row being edited.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [editJob, setEditJob] = useState<JobOut | null>(null);

  const jobs = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const metaOptions = useQuery({ queryKey: ["metaOptions"], queryFn: api.getMetaOptions });

  // In-progress uploads, tracked server-side so the "업로드중" rows survive tab
  // navigation/refresh. Polls while any build is active, then stops.
  const active = useQuery({
    queryKey: ["activeJobs"],
    queryFn: api.getActiveJobs,
    refetchInterval: (q) => ((q.state.data?.length ?? 0) > 0 ? 1000 : false),
  });

  const refreshJobs = () => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["metaOptions"] });
    qc.invalidateQueries({ queryKey: ["activeJobs"] });
  };

  // When a build finishes (drops out of the active list), refresh the job list
  // so the completed row replaces its "업로드중" placeholder.
  const activeIds = (active.data ?? []).map((a) => a.job_id).join(",");
  useEffect(() => {
    qc.invalidateQueries({ queryKey: ["jobs"] });
    qc.invalidateQueries({ queryKey: ["metaOptions"] });
  }, [activeIds, qc]);

  const upload = useMutation({
    mutationFn: ({ file, meta }: { file: File; meta: JobMeta }) =>
      api.uploadJob(file, meta),
    onSuccess: (s, vars) => {
      if (s.status === "ready") {
        message.success(`업로드 완료: ${vars.file.name}`);
        refreshJobs();
      } else {
        message.info(`업로드 시작: ${vars.file.name} — 캐시 빌드 중…`);
        qc.invalidateQueries({ queryKey: ["activeJobs"] });
      }
    },
    onError: (e) => message.error(String(e)),
  });

  const updateMeta = useMutation({
    mutationFn: ({ id, fields }: { id: string; fields: JobMeta }) =>
      api.updateJobMeta(id, fields),
    onSuccess: () => {
      message.success("정보가 수정되었습니다");
      setEditJob(null);
      refreshJobs();
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

  const dim = (v: string) => v || <span style={{ color: "#bbb" }}>—</span>;

  const columns = [
    {
      title: "파일",
      dataIndex: "original_filename",
      render: (v: string, r: JobRow) =>
        r._pending ? (
          <Space size="small">
            <Spin size="small" />
            <span>{v}</span>
            <Tag color="processing">업로드중 {Math.round((r._progress ?? 0) * 100)}%</Tag>
          </Space>
        ) : (
          v
        ),
    },
    { title: "과제", dataIndex: "project", render: dim },
    { title: "타입", dataIndex: "board_type", render: (v: string) => (v ? <Tag>{v}</Tag> : dim(v)) },
    { title: "리비전", dataIndex: "revision", render: dim },
    { title: "단위", dataIndex: "units", render: (u: string) => (u ? <Tag>{u}</Tag> : dim(u)) },
    {
      title: "업로더",
      dataIndex: "uploaded_by",
      render: (u: string) => <Tag color={u && u === user ? "blue" : "default"}>{u || "anonymous"}</Tag>,
    },
    { title: "업로드", dataIndex: "uploaded_at" },
    {
      title: "",
      key: "action",
      render: (_: unknown, r: JobRow) =>
        r._pending ? (
          <span style={{ color: "#aaa", fontSize: 12 }}>처리 중…</span>
        ) : (
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
            <Button
              type="text"
              icon={<EditOutlined />}
              title="과제/타입/리비전 수정"
              onClick={() => setEditJob(r)}
            />
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

  // Merge server-tracked in-progress uploads on top of the fetched jobs.
  const rows = useMemo<JobRow[]>(() => {
    const inScope = (uploadedBy: string) =>
      scope === "all" || !user || uploadedBy === user;
    const base = (jobs.data ?? []).filter((j) => inScope(j.uploaded_by));
    const baseIds = new Set(base.map((j) => j.job_id));
    const pending: JobRow[] = (active.data ?? [])
      .filter((a) => !baseIds.has(a.job_id) && inScope(a.uploaded_by))
      .map((a) => ({
        job_id: a.job_id,
        original_filename: a.original_filename,
        job_name: "",
        project: a.project,
        board_type: a.board_type,
        revision: a.revision,
        units: "",
        odb_version: "",
        data_type: "",
        uploaded_by: a.uploaded_by,
        uploaded_at: "",
        _pending: true,
        _progress: a.progress,
      }));
    return [...pending, ...base];
  }, [jobs.data, active.data, scope, user]);

  return (
    <Card title="대시보드 — ODB++ 업로드 & Job">
      <Upload.Dragger
        accept=".tgz"
        showUploadList={false}
        multiple={false}
        customRequest={({ file, onSuccess }) => {
          // Defer upload until 과제/타입/리비전 are entered in the modal.
          setPendingFile(file as File);
          onSuccess?.({});
        }}
      >
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">ODB++ .tgz 파일을 드래그하거나 클릭하여 업로드</p>
        <p className="ant-upload-hint">업로드 시 과제 · 타입 · 리비전을 입력합니다 (생략 가능)</p>
      </Upload.Dragger>

      <JobMetaModal
        open={!!pendingFile}
        title="ODB++ 데이터 정보 입력"
        okText="업로드"
        options={metaOptions.data}
        confirmLoading={upload.isPending}
        onConfirm={(meta) => {
          if (pendingFile) upload.mutate({ file: pendingFile, meta });
          setPendingFile(null);
        }}
        onCancel={() => setPendingFile(null)}
      />

      <JobMetaModal
        open={!!editJob}
        title="과제 · 타입 · 리비전 수정"
        okText="저장"
        initial={
          editJob
            ? { project: editJob.project, board_type: editJob.board_type, revision: editJob.revision }
            : undefined
        }
        options={metaOptions.data}
        confirmLoading={updateMeta.isPending}
        onConfirm={(fields) => {
          if (editJob) updateMeta.mutate({ id: editJob.job_id, fields });
        }}
        onCancel={() => setEditJob(null)}
      />

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
        dataSource={rows}
        columns={columns}
        expandable={{
          expandedRowRender: (r: JobRow) => <JobResults jobId={r.job_id} />,
          rowExpandable: (r: JobRow) => !r._pending,
        }}
      />
    </Card>
  );
}
