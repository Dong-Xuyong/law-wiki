import { createContext, useContext, type ReactNode } from "react";
import type { MinutasApi } from "./client";

const ApiContext = createContext<MinutasApi | null>(null);

export function ApiProvider({ api, children }: { api: MinutasApi; children: ReactNode }) {
  return <ApiContext.Provider value={api}>{children}</ApiContext.Provider>;
}

export function useApi(): MinutasApi {
  const api = useContext(ApiContext);
  if (!api) throw new Error("A API não está disponível.");
  return api;
}
