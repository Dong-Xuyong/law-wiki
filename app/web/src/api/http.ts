import { ApiError } from "./errors";
import type { MinutasApi } from "./client";
import type {
  Case,
  CreateCaseBody,
  Draft,
  DraftSummary,
  Me,
  Passage,
  ReviewBody,
  ReviewParagraph,
  SourceLines,
} from "../types";

type ErrorBody = {
  error?: unknown;
  message?: unknown;
  remaining?: unknown;
  section?: unknown;
};

function joinUrl(base: string, path: string): string {
  const normalized = base.replace(/\/$/, "");
  return `${normalized}${path.startsWith("/") ? path : `/${path}`}`;
}

async function readError(response: Response): Promise<ApiError> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    body = {};
  }
  const code = typeof body.error === "string" ? body.error : "http_error";
  const message = typeof body.message === "string" ? body.message : "O pedido falhou.";
  return new ApiError(message, response.status, code, {
    remaining: typeof body.remaining === "number" ? body.remaining : undefined,
    section: typeof body.section === "string" ? body.section : undefined,
  });
}

export function createHttpApi(
  apiBase: string,
  getToken: () => Promise<string | null>,
): MinutasApi {
  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const token = await getToken();
    if (!token) {
      throw new ApiError("A sessão expirou. Entre novamente.", 401, "unauthorized");
    }
    const headers = new Headers(init?.headers);
    // Cognito authorizer audience is the app client id, which is the id_token `aud`.
    headers.set("Authorization", `Bearer ${token}`);
    if (init?.body && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(joinUrl(apiBase, path), { ...init, headers });
    if (!response.ok) throw await readError(response);
    return (await response.json()) as T;
  }

  return {
    me: () => request<Me>("/me"),
    async listCases() {
      const data = await request<{ items: Case[] }>("/cases");
      return data.items;
    },
    createCase: (body: CreateCaseBody) =>
      request<{ case: Case; uploadUrl?: string }>("/cases", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    async uploadPdf(uploadUrl: string, file: File) {
      // Presigned S3 URL. Do not send the Cognito bearer: S3 would reject it.
      const response = await fetch(uploadUrl, {
        method: "PUT",
        headers: { "Content-Type": "application/pdf" },
        body: file,
      });
      if (!response.ok) {
        throw new ApiError("Não foi possível carregar o PDF.", response.status, "upload_failed");
      }
    },
    getCase: (caseId: string) =>
      request<{ case: Case; drafts: DraftSummary[] }>(`/cases/${encodeURIComponent(caseId)}`),
    createDraft: (caseId: string) =>
      request<{ draftId: string; status: "queued" }>(
        `/cases/${encodeURIComponent(caseId)}/drafts`,
        { method: "POST" },
      ),
    getDraft: (draftId: string) => request<Draft>(`/drafts/${encodeURIComponent(draftId)}`),
    reviewParagraph: (draftId: string, paragraphId: string, body: ReviewBody) =>
      request<ReviewParagraph>(
        `/drafts/${encodeURIComponent(draftId)}/paragraphs/${encodeURIComponent(paragraphId)}`,
        { method: "PATCH", body: JSON.stringify(body) },
      ),
    exportDraft: (draftId: string) =>
      request<{ url: string }>(`/drafts/${encodeURIComponent(draftId)}/export`, {
        method: "POST",
      }),
    async search(query: string, k = 8) {
      const params = new URLSearchParams({ q: query, k: String(k) });
      const data = await request<{ items: Passage[] }>(`/search?${params.toString()}`);
      return data.items;
    },
    sourceLines: (documentId: string, start: number, end: number) => {
      const params = new URLSearchParams({ start: String(start), end: String(end) });
      return request<SourceLines>(
        `/sources/${encodeURIComponent(documentId)}/lines?${params.toString()}`,
      );
    },
  };
}
