// Shared "current job" so a job selected on the Dashboard carries over to the
// feature pages (the core hub UX: cache once, use everywhere).

import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";

interface JobCtx {
  jobId: string | null;
  setJobId: (id: string | null) => void;
}

const Ctx = createContext<JobCtx>({ jobId: null, setJobId: () => {} });

export function JobProvider({ children }: { children: ReactNode }) {
  const [jobId, setJobId] = useState<string | null>(null);
  return <Ctx.Provider value={{ jobId, setJobId }}>{children}</Ctx.Provider>;
}

export const useJob = () => useContext(Ctx);
