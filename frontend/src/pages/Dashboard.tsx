import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App as AntdApp,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Upload,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  InboxOutlined,
  LockOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import JobMetaModal from "../components/JobMetaModal";
import { useJob } from "../JobContext";
import type { JobMeta, JobOut } from "../types";

// A table row is a fetched job, optionally an in-progress upload placeholder
// (_pending) carrying its live build progress (0–1).
type JobRow = JobOut & { _pending?: boolean; _progress?: number };

// Verified manager password cached for the browser session so repeated deletes
// don't re-prompt (same key/flow as the 사용자 현황 page).
const PW_KEY = "odbhub.managerpw";

// Searchable fields for the dashboard filter (default = 파일).
const SEARCH_FIELDS: { label: string; value: keyof JobOut }[] = [
  { label: "파일", value: "original_filename" },
  { label: "과제", value: "project" },
  { label: "모델", value: "model" },
  { label: "타입", value: "board_type" },
];

// Format a UTC ISO timestamp as Korean local time "YYYY-MM-DD / HH:MM:SS".
function fmtKST(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} / ${get("hour")}:${get("minute")}:${get("second")}`;
}

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
  const { message } = AntdApp.useApp();
  // Search filter (left select + term).
  const [searchField, setSearchField] = useState<keyof JobOut>("original_filename");
  const [searchTerm, setSearchTerm] = useState("");
  // File awaiting metadata entry before upload; job row being edited.
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [editJob, setEditJob] = useState<JobOut | null>(null);
  // Job pending deletion (awaiting password confirmation).
  const [deleteTarget, setDeleteTarget] = useState<JobRow | null>(null);
  const [pwInput, setPwInput] = useState("");
  const [pwError, setPwError] = useState("");

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
    mutationFn: ({ id, pw }: { id: string; pw: string }) => api.deleteJob(id, pw),
    onSuccess: (_d, vars) => {
      sessionStorage.setItem(PW_KEY, vars.pw);
      message.success("삭제되었습니다");
      if (currentJobId === vars.id) setJobId(null);
      setDeleteTarget(null);
      setPwInput("");
      setPwError("");
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (e) =>
      setPwError(
        String(e).includes("401") ? "비밀번호가 올바르지 않습니다." : String(e),
      ),
  });

  const openDelete = (r: JobRow) => {
    setPwInput(sessionStorage.getItem(PW_KEY) || "");
    setPwError("");
    setDeleteTarget(r);
  };
  const confirmDelete = () => {
    if (deleteTarget && pwInput) remove.mutate({ id: deleteTarget.job_id, pw: pwInput });
  };

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
    { title: "모델", dataIndex: "model", render: dim },
    { title: "타입", dataIndex: "board_type", render: (v: string) => (v ? <Tag>{v}</Tag> : dim(v)) },
    { title: "리비전", dataIndex: "revision", render: dim },
    { title: "단위", dataIndex: "units", render: (u: string) => (u ? <Tag>{u}</Tag> : dim(u)) },
    { title: "업로드", dataIndex: "uploaded_at", render: (t: string) => fmtKST(t) || dim(t) },
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
              title="과제/모델/타입/리비전 수정"
              onClick={() => setEditJob(r)}
            />
            <Button
              type="text"
              danger
              icon={<DeleteOutlined />}
              title="삭제 (비밀번호 필요)"
              onClick={() => openDelete(r)}
            />
          </Space>
        ),
    },
  ];

  // Merge server-tracked in-progress uploads on top of the fetched jobs.
  // Jobs are filtered by the search box and sorted by upload time (newest first);
  // in-progress uploads always stay pinned on top.
  const rows = useMemo<JobRow[]>(() => {
    const term = searchTerm.trim().toLowerCase();
    const match = (j: Pick<JobOut, keyof JobOut>) =>
      !term || String((j[searchField] ?? "")).toLowerCase().includes(term);
    const base = (jobs.data ?? [])
      .filter(match)
      .sort((a, b) => (b.uploaded_at || "").localeCompare(a.uploaded_at || ""));
    const baseIds = new Set(base.map((j) => j.job_id));
    const pending: JobRow[] = (active.data ?? [])
      .filter((a) => !baseIds.has(a.job_id))
      .map((a) => ({
        job_id: a.job_id,
        original_filename: a.original_filename,
        job_name: "",
        project: a.project,
        model: a.model,
        board_type: a.board_type,
        revision: a.revision,
        units: "",
        odb_version: "",
        data_type: "",
        uploaded_by: a.uploaded_by,
        uploaded_at: "",
        _pending: true,
        _progress: a.progress,
      }))
      .filter((r) => match(r));
    return [...pending, ...base];
  }, [jobs.data, active.data, searchField, searchTerm]);

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
        <p className="ant-upload-hint">업로드 시 과제 · 모델 · 타입 · 리비전을 입력합니다 (생략 가능)</p>
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
        title="과제 · 모델 · 타입 · 리비전 수정"
        okText="저장"
        initial={
          editJob
            ? {
                project: editJob.project,
                model: editJob.model,
                board_type: editJob.board_type,
                revision: editJob.revision,
              }
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
        <Input.Search
          allowClear
          enterButton="검색"
          placeholder="검색어 입력"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          onSearch={(v) => setSearchTerm(v)}
          addonBefore={
            <Select
              value={searchField}
              onChange={setSearchField}
              options={SEARCH_FIELDS}
              style={{ width: 88 }}
            />
          }
          style={{ maxWidth: 440 }}
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

      <Modal
        open={!!deleteTarget}
        title="데이터 삭제"
        okText="삭제"
        okButtonProps={{ danger: true, loading: remove.isPending, disabled: !pwInput }}
        cancelText="취소"
        onOk={confirmDelete}
        onCancel={() => setDeleteTarget(null)}
      >
        <p>
          <b>{deleteTarget?.original_filename}</b> 을(를) 삭제합니다. 소스/캐시/리포트가 모두
          삭제됩니다.
        </p>
        <p style={{ color: "#888" }}>삭제하려면 관리자 비밀번호를 입력하세요.</p>
        <Input.Password
          prefix={<LockOutlined />}
          placeholder="비밀번호"
          value={pwInput}
          onChange={(e) => {
            setPwInput(e.target.value);
            setPwError("");
          }}
          onPressEnter={confirmDelete}
          autoFocus
        />
        {pwError && <Alert type="error" message={pwError} style={{ marginTop: 12 }} />}
      </Modal>
    </Card>
  );
}
