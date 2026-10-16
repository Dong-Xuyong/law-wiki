export type AppConfig = {
  apiBase: string;
  region: string;
  userPoolId: string;
  clientId: string;
  cognitoDomain: string;
  redirectUri: string;
};

export type Me = {
  sub: string;
  email: string;
};

export type CaseStatus = "new" | "ready";
export type InputKind = "text" | "pdf";

export type Case = {
  caseId: string;
  title: string;
  inputKind: InputKind;
  status: CaseStatus;
  createdAt: string;
  updatedAt: string;
};

export type DraftStatus = "queued" | "running" | "ready" | "failed";

export type DraftSummary = {
  draftId: string;
  status: DraftStatus;
  createdAt: string;
};

export type Confidence = "high" | "medium" | "low";

export type ReviewStatus = "pending" | "accepted" | "edited" | "rejected";

export type ReviewState = {
  status: ReviewStatus;
  by: string;
  at: string;
};

export type ReviewParagraph = {
  id: string;
  section: string;
  index: number;
  text: string;
  sourceIds: string[];
  evidenceIds: string[];
  confidence: Confidence;
  note: string;
  originalText: string;
  review: ReviewState;
};

export type Source = {
  id: string;
  title: string;
  path: string;
  document_id: string;
  pinpoints: string[];
};

export type EvidenceItem = {
  id: string;
  proposition: string;
  status: "proved" | "procedural" | "not_proved";
  basis: string;
};

export type Amount = {
  item: string;
  claimed: string;
  awarded: string;
  reason: string;
};

export type Draft = {
  draftId: string;
  caseId: string;
  status: DraftStatus;
  error?: string;
  modelId: string;
  createdAt: string;
  evidence: EvidenceItem[];
  sources: Source[];
  amounts: Amount[];
  decisionTotal: string;
  paragraphs: ReviewParagraph[];
  reviewedCount: number;
  totalCount: number;
};

export type Passage = {
  document_id: string;
  path: string;
  title: string;
  line_start: number;
  line_end: number;
  text: string;
  score: number;
};

export type SourceLines = {
  documentId: string;
  title: string;
  path: string;
  lineStart: number;
  lineEnd: number;
  text: string;
  publicUrl: string;
};

export type CreateCaseBody = {
  title: string;
  text?: string;
  inputKind: InputKind;
  fictional: true;
};

export type ReviewAction = "accept" | "edit" | "reject";

export type ReviewBody = {
  action: ReviewAction;
  text?: string;
};
