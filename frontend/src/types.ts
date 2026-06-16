// Mirrors the FastAPI Pydantic schemas (api/schemas.py).
// Could be auto-generated later via openapi-typescript.

export interface JobOut {
  job_id: string;
  original_filename: string;
  job_name: string;
  units: string;
  odb_version: string;
  data_type: string;
  uploaded_at: string;
}

export interface JobStatus {
  job_id: string;
  status: string; // caching | ready | error | unknown
  progress: number;
  message: string;
  error: string | null;
}

export interface TaskOut {
  task_id: string;
  kind: string;
  job_id: string | null;
  status: string; // queued | running | done | error
  progress: number;
  message: string;
  result: Record<string, unknown>;
  error: string | null;
}

export interface ResultOut {
  kind: string;
  report: string | null;
  summary: Record<string, unknown>;
  params: Record<string, unknown>;
  completed_at: string;
}

export interface RuleInfo {
  rule_id: string;
  description: string;
  category: string;
}

export interface LayerInfo {
  name: string;
  type: string;
}

export interface PolyMeta {
  refdes: string;
  part: string;
  category: string;
}

export interface Ring {
  exterior: [number, number][];
  holes: [number, number][][];
  color?: string;
  fill?: boolean; // false = stroke only (e.g. component package outlines)
  meta?: PolyMeta;
}

export interface LayerGeometry {
  bounds: [number, number, number, number];
  profile: Ring[];
  polygons: Ring[];
  points?: [number, number][];
  layer?: string;
  type?: string;
  net?: string;
  side?: string;
}
