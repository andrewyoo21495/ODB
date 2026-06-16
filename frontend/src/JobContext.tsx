// Shared "current job" so a job selected on the Dashboard carries over to the
// feature pages (the core hub UX: cache once, use everywhere).

import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

interface JobCtx {
  jobId: string | null;
  setJobId: (id: string | null) => void;
}

const Ctx = createContext<JobCtx>({ jobId: null, setJobId: () => {} });

const STORAGE_KEY = "odbhub.jobId";

export function JobProvider({ children }: { children: ReactNode }) {
  // Persist the selected job so it survives page refresh / new tabs.
  const [jobId, setJobId] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY),
  );
  useEffect(() => {
    if (jobId) localStorage.setItem(STORAGE_KEY, jobId);
    else localStorage.removeItem(STORAGE_KEY);
  }, [jobId]);
  return <Ctx.Provider value={{ jobId, setJobId }}>{children}</Ctx.Provider>;
}

export const useJob = () => useContext(Ctx);
