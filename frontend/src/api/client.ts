// Thin fetch wrapper over the FastAPI backend (proxied at /api in dev).

import type { ActiveJob, ActivityOut, ComponentInfo, JobMeta, JobOut, JobStatus, LayerGeometry, LayerInfo, MetaOptions, ResultOut, RuleInfo, TaskOut } from "../types";

const BASE = "/api";

// Self-declared display name (no auth) sent on every request so the backend can
// tag job/result ownership and the UI can filter "my jobs".
const USER_KEY = "odbhub.user";
export const getUser = () => localStorage.getItem(USER_KEY) || "";
export const setUser = (name: string) => {
  if (name) localStorage.setItem(USER_KEY, name);
  else localStorage.removeItem(USER_KEY);
};
function userHeaders(extra?: Record<string, string>): Record<string, string> {
  const u = getUser();
  return { ...(u ? { "X-User": u } : {}), ...(extra ?? {}) };
}

async function jsonGet<T>(url: string): Promise<T> {
  const r = await fetch(BASE + url, { headers: userHeaders() });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

async function jsonPost<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + url, {
    method: "POST",
    headers: userHeaders({ "Content-Type": "application/json" }),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

async function jsonPatch<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + url, {
    method: "PATCH",
    headers: userHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  uploadJob: async (file: File, meta?: Partial<JobMeta>): Promise<JobStatus> => {
    const fd = new FormData();
    fd.append("file", file);
    if (meta?.project) fd.append("project", meta.project);
    if (meta?.board_type) fd.append("board_type", meta.board_type);
    if (meta?.revision) fd.append("revision", meta.revision);
    const r = await fetch(BASE + "/jobs", { method: "POST", body: fd, headers: userHeaders() });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json() as Promise<JobStatus>;
  },
  listJobs: () => jsonGet<JobOut[]>("/jobs"),
  getActiveJobs: () => jsonGet<ActiveJob[]>("/jobs/active"),
  getJob: (id: string) => jsonGet<JobOut>(`/jobs/${id}`),
  getMetaOptions: () => jsonGet<MetaOptions>("/jobs/meta/options"),
  updateJobMeta: (id: string, fields: JobMeta) =>
    jsonPatch<JobOut>(`/jobs/${id}/meta`, fields),
  deleteJob: async (id: string): Promise<void> => {
    const r = await fetch(`${BASE}/jobs/${id}`, { method: "DELETE", headers: userHeaders() });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  },
  getActivity: async (limit = 200, pw = ""): Promise<ActivityOut> => {
    const r = await fetch(`${BASE}/activity?limit=${limit}`, {
      headers: userHeaders(pw ? { "X-Manager-Pw": pw } : undefined),
    });
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json() as Promise<ActivityOut>;
  },
  jobStatus: (id: string) => jsonGet<JobStatus>(`/jobs/${id}/status`),
  getResults: (id: string) => jsonGet<ResultOut[]>(`/jobs/${id}/results`),
  getLatestTask: (id: string, kind: string) =>
    jsonGet<TaskOut | null>(`/jobs/${id}/tasks/${kind}`),
  // Report served by job+kind (independent of an in-memory task).
  reportByKindUrl: (id: string, kind: string) => `${BASE}/jobs/${id}/report/${kind}`,
  jobArtifactUrl: (id: string, name: string) => `${BASE}/jobs/${id}/artifact/${name}`,
  getRules: () => jsonGet<RuleInfo[]>("/rules"),
  runChecklist: (id: string, ruleIds: string[] | null) =>
    jsonPost<TaskOut>(`/jobs/${id}/checklist`, { rule_ids: ruleIds }),
  runCopper: (id: string, body: { method: string; n_rows: number; n_cols: number }) =>
    jsonPost<TaskOut>(`/jobs/${id}/copper`, body),
  runExtract: (id: string, categories: string[] | null) =>
    jsonPost<TaskOut>(`/jobs/${id}/extract`, { categories }),
  runInterposer: (id: string) => jsonPost<TaskOut>(`/jobs/${id}/interposer`),
  runCompare: (oldJobId: string, newJobId: string) =>
    jsonPost<TaskOut>(`/compare`, { old_job_id: oldJobId, new_job_id: newJobId }),
  getLayers: (id: string) => jsonGet<LayerInfo[]>(`/jobs/${id}/layers`),
  getNets: (id: string, layer: string) =>
    jsonGet<string[]>(`/jobs/${id}/nets?layer=${encodeURIComponent(layer)}`),
  getComponents: (id: string, side: string) =>
    jsonGet<ComponentInfo[]>(`/jobs/${id}/components?side=${encodeURIComponent(side)}`),
  runViewer: (id: string, layer: string) =>
    jsonPost<TaskOut>(`/jobs/${id}/viewer`, { layer }),
  runViewerNet: (id: string, layer: string, net: string) =>
    jsonPost<TaskOut>(`/jobs/${id}/viewer/net`, { layer, net }),
  runViewerComponent: (id: string, side: string, refdes: string[] | null) =>
    jsonPost<TaskOut>(`/jobs/${id}/viewer/component`, { side, refdes }),
  fetchGeometry: async (taskId: string, name: string): Promise<LayerGeometry> => {
    const r = await fetch(`${BASE}/tasks/${taskId}/artifact/${name}`);
    if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
    return r.json() as Promise<LayerGeometry>;
  },
  artifactUrl: (taskId: string, name: string) =>
    `${BASE}/tasks/${taskId}/artifact/${name}`,
  getTask: (id: string) => jsonGet<TaskOut>(`/tasks/${id}`),
  reportUrl: (taskId: string) => `${BASE}/tasks/${taskId}/report`,
};
