import { SECTION_ORDER } from "../lib/labels";
import { ApiError } from "./errors";
import type { MinutasApi } from "./client";
import {
  buildDraftBody,
  lookupLines,
  MOCK_EMAIL,
  MOCK_SUB,
  MODEL_ID,
  PUBLIC_ORIGIN,
  searchCorpus,
} from "./sample";
import type {
  Case,
  CreateCaseBody,
  Draft,
  DraftStatus,
  DraftSummary,
  ReviewBody,
  ReviewParagraph,
} from "../types";

const MAX_PDF_BYTES = 15 * 1024 * 1024;
const SEED_TITLE = "Caso fictício: atraso do voo AN 5520 (Porto–Milão)";

type StoredCase = Case & { text: string; pdfStored: boolean };

type StoredDraft = {
  phase: "static" | "job";
  startedAt: number;
  draft: Draft;
};

const cases = new Map<string, StoredCase>();
const drafts = new Map<string, StoredDraft>();

function nowIso(): string {
  return new Date().toISOString();
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

function newId(prefix: "c" | "d", taken: { has(id: string): boolean }): string {
  const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789";
  let id = "";
  do {
    const bytes = crypto.getRandomValues(new Uint8Array(10));
    let body = "";
    for (const byte of bytes) body += alphabet[byte % alphabet.length];
    id = `${prefix}_${body}`;
  } while (taken.has(id));
  return id;
}

function publicCase(stored: StoredCase): Case {
  return {
    caseId: stored.caseId,
    title: stored.title,
    inputKind: stored.inputKind,
    status: stored.status,
    createdAt: stored.createdAt,
    updatedAt: stored.updatedAt,
  };
}

function counts(paragraphs: ReviewParagraph[]): { reviewedCount: number; totalCount: number } {
  return {
    reviewedCount: paragraphs.filter((paragraph) => paragraph.review.status !== "pending").length,
    totalCount: paragraphs.length,
  };
}

function phaseStatus(record: StoredDraft): DraftStatus {
  if (record.phase === "static") return record.draft.status;
  const elapsed = Date.now() - record.startedAt;
  if (elapsed < 5000) return "queued";
  if (elapsed < 10000) return "running";
  return "ready";
}

function present(record: StoredDraft): Draft {
  const status = phaseStatus(record);
  if (record.phase === "static" || status === "ready") {
    const ready = clone(record.draft);
    ready.status = status === "ready" && record.phase === "job" ? "ready" : record.draft.status;
    if (record.phase === "job") {
      ready.status = "ready";
      ready.modelId = MODEL_ID;
      delete ready.error;
    }
    return ready;
  }
  return {
    ...clone(record.draft),
    status,
    modelId: "",
    evidence: [],
    sources: [],
    amounts: [],
    decisionTotal: "0.00",
    paragraphs: [],
    reviewedCount: 0,
    totalCount: 0,
    error: undefined,
  };
}

function summary(draft: Draft): DraftSummary {
  return { draftId: draft.draftId, status: draft.status, createdAt: draft.createdAt };
}

function requireCase(caseId: string): StoredCase {
  const stored = cases.get(caseId);
  if (!stored) throw new ApiError("Caso não encontrado.", 404, "not_found");
  return stored;
}

function requireDraft(draftId: string): StoredDraft {
  const stored = drafts.get(draftId);
  if (!stored) throw new ApiError("Minuta não encontrada.", 404, "not_found");
  return stored;
}

function applyDemoReviews(paragraphs: ReviewParagraph[]): ReviewParagraph[] {
  return paragraphs.map((paragraph) => {
    if (paragraph.id === "sumario-0") {
      return {
        ...paragraph,
        review: { status: "accepted", by: MOCK_SUB, at: "2026-10-15T11:04:00.000Z" },
      };
    }
    if (paragraph.id === "relatorio-1") {
      return {
        ...paragraph,
        text: `${paragraph.text} A alteração do pedido ficou registada em audiência.`,
        review: { status: "edited", by: MOCK_SUB, at: "2026-10-15T11:06:00.000Z" },
      };
    }
    if (paragraph.id === "factos_nao_provados-2") {
      return {
        ...paragraph,
        review: { status: "rejected", by: MOCK_SUB, at: "2026-10-15T11:08:00.000Z" },
      };
    }
    if (paragraph.id === "decisao-0") {
      return {
        ...paragraph,
        review: { status: "accepted", by: MOCK_SUB, at: "2026-10-15T11:10:00.000Z" },
      };
    }
    return paragraph;
  });
}

function makeDraft(caseId: string, draftId: string, title: string, createdAt: string): Draft {
  const body = buildDraftBody(title);
  return {
    draftId,
    caseId,
    status: "ready",
    modelId: MODEL_ID,
    createdAt,
    evidence: body.evidence,
    sources: body.sources,
    amounts: body.amounts,
    decisionTotal: body.decisionTotal,
    paragraphs: body.paragraphs,
    ...counts(body.paragraphs),
  };
}

function seed(): void {
  if (cases.size > 0) return;
  const caseId = "c_atraso5520";
  cases.set(caseId, {
    caseId,
    title: SEED_TITLE,
    inputKind: "text",
    status: "ready",
    createdAt: "2026-10-15T09:00:00.000Z",
    updatedAt: "2026-10-15T11:10:00.000Z",
    text: "Registo fictício do voo AN 5520, Porto–Milão Malpensa.",
    pdfStored: false,
  });

  const ready = makeDraft(caseId, "d_pronta5520", SEED_TITLE, "2026-10-15T10:30:00.000Z");
  ready.paragraphs = applyDemoReviews(ready.paragraphs);
  const readyCounts = counts(ready.paragraphs);
  ready.reviewedCount = readyCounts.reviewedCount;
  ready.totalCount = readyCounts.totalCount;
  drafts.set(ready.draftId, { phase: "static", startedAt: 0, draft: ready });

  drafts.set("d_falhou5520", {
    phase: "static",
    startedAt: 0,
    draft: {
      draftId: "d_falhou5520",
      caseId,
      status: "failed",
      error: "O modelo não devolveu um pacote válido após duas reparações. Nada foi gravado como minuta final.",
      modelId: MODEL_ID,
      createdAt: "2026-10-15T10:00:00.000Z",
      evidence: [],
      sources: [],
      amounts: [],
      decisionTotal: "0.00",
      paragraphs: [],
      reviewedCount: 0,
      totalCount: 0,
    },
  });
}

function draftsFor(caseId: string): DraftSummary[] {
  return [...drafts.values()]
    .map((record) => present(record))
    .filter((draft) => draft.caseId === caseId)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .map(summary);
}

function assertExportable(draft: Draft): void {
  const pending = draft.paragraphs.filter((paragraph) => paragraph.review.status === "pending");
  if (pending.length > 0) {
    throw new ApiError("Ainda há parágrafos por rever.", 409, "unreviewed", {
      remaining: pending.length,
    });
  }
  for (const section of SECTION_ORDER) {
    const alive = draft.paragraphs.filter(
      (paragraph) => paragraph.section === section && paragraph.review.status !== "rejected",
    );
    if (alive.length === 0) {
      throw new ApiError("Uma secção obrigatória ficaria vazia.", 409, "section_empty", {
        section,
      });
    }
  }
}

let singleton: MinutasApi | null = null;

export function createMockApi(): MinutasApi {
  if (singleton) return singleton;
  seed();
  singleton = {
    async me() {
      return { sub: MOCK_SUB, email: MOCK_EMAIL };
    },
    async listCases() {
      return [...cases.values()]
        .map(publicCase)
        .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
    },
    async createCase(body: CreateCaseBody) {
      if (body.fictional !== true) {
        throw new ApiError(
          "É obrigatório confirmar que o caso é fictício ou uma decisão publicada.",
          400,
          "fictional_required",
        );
      }
      const title = body.title.trim();
      if (!title) throw new ApiError("Indique o título do caso.", 400, "title_required");
      if (body.inputKind === "text" && !body.text?.trim()) {
        throw new ApiError("Cole o texto do caso.", 400, "text_required");
      }
      const createdAt = nowIso();
      const caseId = newId("c", cases);
      const stored: StoredCase = {
        caseId,
        title,
        inputKind: body.inputKind,
        status: body.inputKind === "text" ? "ready" : "new",
        createdAt,
        updatedAt: createdAt,
        text: body.inputKind === "text" ? body.text?.trim() ?? "" : "",
        pdfStored: false,
      };
      cases.set(caseId, stored);
      return {
        case: publicCase(stored),
        uploadUrl: body.inputKind === "pdf" ? `mock:upload:${caseId}` : undefined,
      };
    },
    async uploadPdf(uploadUrl: string, file: File) {
      if (!uploadUrl.startsWith("mock:upload:")) {
        throw new ApiError("Endereço de carregamento inválido.", 400, "bad_upload");
      }
      const stored = requireCase(uploadUrl.slice("mock:upload:".length));
      const name = file.name.toLowerCase();
      const pdfType = !file.type || file.type === "application/pdf" || file.type === "application/x-pdf";
      if (!name.endsWith(".pdf") || !pdfType) {
        throw new ApiError("O ficheiro tem de ser um PDF.", 400, "pdf_required");
      }
      if (file.size > MAX_PDF_BYTES) {
        throw new ApiError("O PDF não pode exceder 15 MB.", 400, "pdf_too_large");
      }
      stored.pdfStored = true;
      stored.status = "ready";
      stored.text = `PDF fictício carregado: ${file.name}`;
      stored.updatedAt = nowIso();
    },
    async getCase(caseId: string) {
      const stored = requireCase(caseId);
      return { case: publicCase(stored), drafts: draftsFor(caseId) };
    },
    async createDraft(caseId: string) {
      const stored = requireCase(caseId);
      if (!stored.text && !stored.pdfStored) {
        throw new ApiError("O caso ainda não tem texto nem PDF.", 400, "input_missing");
      }
      const draftId = newId("d", drafts);
      const createdAt = nowIso();
      const draft = makeDraft(caseId, draftId, stored.title, createdAt);
      drafts.set(draftId, { phase: "job", startedAt: Date.now(), draft });
      stored.updatedAt = createdAt;
      return { draftId, status: "queued" as const };
    },
    async getDraft(draftId: string) {
      return present(requireDraft(draftId));
    },
    async reviewParagraph(draftId: string, paragraphId: string, body: ReviewBody) {
      const record = requireDraft(draftId);
      if (phaseStatus(record) !== "ready") {
        throw new ApiError("A minuta ainda não está pronta para revisão.", 409, "not_ready");
      }
      const current = record.draft.paragraphs.find((paragraph) => paragraph.id === paragraphId);
      if (!current) throw new ApiError("Parágrafo não encontrado.", 404, "not_found");
      const next: ReviewParagraph = { ...current, review: { ...current.review } };
      const at = nowIso();
      if (body.action === "edit") {
        const text = body.text ?? "";
        if (!text.trim()) {
          throw new ApiError("O texto revisto não pode ficar vazio.", 400, "text_required");
        }
        next.text = text;
        next.review = { status: "edited", by: MOCK_SUB, at };
      } else if (body.action === "accept") {
        next.review = { status: "accepted", by: MOCK_SUB, at };
      } else if (body.action === "reject") {
        next.review = { status: "rejected", by: MOCK_SUB, at };
      } else {
        throw new ApiError("Ação de revisão desconhecida.", 400, "bad_action");
      }
      record.draft.paragraphs = record.draft.paragraphs.map((paragraph) =>
        paragraph.id === paragraphId ? next : paragraph,
      );
      const nextCounts = counts(record.draft.paragraphs);
      record.draft.reviewedCount = nextCounts.reviewedCount;
      record.draft.totalCount = nextCounts.totalCount;
      return clone(next);
    },
    async exportDraft(draftId: string) {
      const record = requireDraft(draftId);
      const draft = present(record);
      if (draft.status !== "ready") {
        throw new ApiError("A minuta ainda não está pronta para exportação.", 409, "not_ready");
      }
      assertExportable(draft);
      const kept = draft.paragraphs.filter((paragraph) => paragraph.review.status !== "rejected");
      const lines = [
        "MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA",
        "",
        ...kept.map((paragraph) => paragraph.text),
        "",
        "Decisão produzida com o auxílio de sistema de IA, de acordo com as recomendações do CSM. Integralmente revisto pelo signatário.",
      ];
      const blob = new Blob([lines.join("\n\n")], { type: "text/plain;charset=utf-8" });
      return { url: URL.createObjectURL(blob) };
    },
    async search(query: string, k = 8) {
      const trimmed = query.trim();
      if (!trimmed) throw new ApiError("Indique o texto a pesquisar.", 400, "query_required");
      const size = Math.min(Math.max(k, 1), 20);
      return searchCorpus(trimmed, size);
    },
    async sourceLines(documentId: string, start: number, end: number) {
      if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end < start) {
        throw new ApiError("Intervalo de linhas inválido.", 400, "bad_range");
      }
      if (end - start + 1 > 200) {
        throw new ApiError("O intervalo não pode exceder 200 linhas.", 400, "range_too_wide");
      }
      const record = lookupLines(documentId, start, end);
      if (!record) throw new ApiError("Passagem não encontrada.", 404, "not_found");
      return {
        documentId,
        title: record.title,
        path: record.path,
        lineStart: start,
        lineEnd: end,
        text: record.text,
        publicUrl: `${PUBLIC_ORIGIN}/${documentId}/`,
      };
    },
  };
  return singleton;
}
