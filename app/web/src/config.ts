import type { AppConfig } from "./types";

const KEYS = [
  "apiBase",
  "region",
  "userPoolId",
  "clientId",
  "cognitoDomain",
  "redirectUri",
] as const;

export async function loadConfig(): Promise<AppConfig> {
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Não foi possível ler a configuração.");
  }
  const data: unknown = await response.json();
  if (!data || typeof data !== "object") {
    throw new Error("A configuração não é um objeto JSON.");
  }
  const record = data as Record<string, unknown>;
  const config = {} as AppConfig;
  for (const key of KEYS) {
    const value = record[key];
    if (typeof value !== "string" || value.trim() === "") {
      throw new Error(`A configuração não tem «${key}».`);
    }
    config[key] = value.trim();
  }
  if (config.apiBase !== "mock") {
    config.apiBase = config.apiBase.replace(/\/$/, "");
  }
  return config;
}

export function isMockConfig(config: AppConfig): boolean {
  return config.apiBase === "mock";
}
