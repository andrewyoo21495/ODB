// Self-declared user identity (no auth). Stored in localStorage and sent as the
// X-User header by the API client; held in context so the UI reacts to changes
// (e.g. the dashboard "my jobs" filter).

import { createContext, useContext, useState } from "react";
import type { ReactNode } from "react";
import { getUser, setUser } from "./api/client";

interface UserCtx {
  user: string;
  setUserName: (name: string) => void;
}

const Ctx = createContext<UserCtx>({ user: "", setUserName: () => {} });

export function UserProvider({ children }: { children: ReactNode }) {
  const [user, setUserState] = useState<string>(() => getUser());
  const setUserName = (name: string) => {
    const v = name.trim();
    setUser(v);
    setUserState(v);
  };
  return <Ctx.Provider value={{ user, setUserName }}>{children}</Ctx.Provider>;
}

export const useUser = () => useContext(Ctx);
