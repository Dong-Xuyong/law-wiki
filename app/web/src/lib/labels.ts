import type { Confidence, DraftStatus, ReviewStatus } from "../types";

export const SECTION_ORDER = [
  "sumario",
  "relatorio",
  "objeto_litigio",
  "saneador",
  "factos_provados",
  "factos_nao_provados",
  "motivacao",
  "fundamentacao_direito",
  "decisao",
] as const;

export type SectionId = (typeof SECTION_ORDER)[number];

export const SECTION_LABEL: Record<SectionId, string> = {
  sumario: "Sumário",
  relatorio: "I Relatório",
  objeto_litigio: "II Objeto do litígio",
  saneador: "III Saneador",
  factos_provados: "IV Factos provados",
  factos_nao_provados: "Factos não provados",
  motivacao: "V Motivação",
  fundamentacao_direito: "VI Fundamentação de direito",
  decisao: "VII Decisão",
};

export function sectionLabel(section: string): string {
  if (section in SECTION_LABEL) return SECTION_LABEL[section as SectionId];
  return section || "Secção desconhecida";
}

export function confidenceLabel(confidence: Confidence): string {
  if (confidence === "high") return "Alta";
  if (confidence === "medium") return "Média";
  return "Baixa";
}

export function reviewLabel(status: ReviewStatus): string {
  if (status === "accepted") return "Aceite";
  if (status === "edited") return "Editado";
  if (status === "rejected") return "Rejeitado";
  return "Por rever";
}

export function draftStatusLabel(status: DraftStatus | string): string {
  if (status === "queued") return "Em fila";
  if (status === "running") return "A gerar";
  if (status === "ready") return "Pronta";
  if (status === "failed") return "Falhou";
  return status;
}

export function caseStatusLabel(status: string): string {
  if (status === "new") return "Novo";
  if (status === "ready") return "Pronto";
  return status;
}

export function inputKindLabel(kind: string): string {
  if (kind === "pdf") return "PDF";
  if (kind === "text") return "Texto";
  return kind;
}

const BASIS_LABEL: Record<string, string> = {
  common: "Comum",
  admission: "Admissão",
  procedural_record: "Registo processual",
  unilateral_assertion: "Alegação unilateral",
  unseen_attachment: "Anexo não junto",
};

export function basisLabel(basis: string): string {
  return BASIS_LABEL[basis] ?? basis;
}

export function evidenceStatusLabel(status: string): string {
  if (status === "proved") return "Provado";
  if (status === "procedural") return "Processual";
  if (status === "not_proved") return "Não provado";
  return status;
}
