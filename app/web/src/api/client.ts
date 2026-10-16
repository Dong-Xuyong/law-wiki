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

export type MinutasApi = {
  me(): Promise<Me>;
  listCases(): Promise<Case[]>;
  createCase(body: CreateCaseBody): Promise<{ case: Case; uploadUrl?: string }>;
  uploadPdf(uploadUrl: string, file: File): Promise<void>;
  getCase(caseId: string): Promise<{ case: Case; drafts: DraftSummary[] }>;
  createDraft(caseId: string): Promise<{ draftId: string; status: "queued" }>;
  getDraft(draftId: string): Promise<Draft>;
  reviewParagraph(
    draftId: string,
    paragraphId: string,
    body: ReviewBody,
  ): Promise<ReviewParagraph>;
  exportDraft(draftId: string): Promise<{ url: string }>;
  search(query: string, k?: number): Promise<Passage[]>;
  sourceLines(documentId: string, start: number, end: number): Promise<SourceLines>;
};
