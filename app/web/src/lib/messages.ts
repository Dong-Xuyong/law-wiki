import { ApiError } from "../api/errors";
import { sectionLabel } from "./labels";

export function exportFailure(error: ApiError): string | null {
  if (error.code === "unreviewed") {
    const remaining = error.remaining ?? 0;
    if (remaining === 1) {
      return "Falta rever 1 parágrafo. A exportação só é possível quando todos os parágrafos tiverem sido revistos.";
    }
    return `Faltam rever ${remaining} parágrafos. A exportação só é possível quando todos os parágrafos tiverem sido revistos.`;
  }
  if (error.code === "section_empty") {
    const label = sectionLabel(error.section ?? "");
    return `A secção «${label}» ficaria vazia. Aceite ou edite pelo menos um parágrafo dessa secção.`;
  }
  return null;
}

export function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "fictional_required") {
      return "É obrigatório confirmar que o caso é fictício ou uma decisão publicada.";
    }
    const mapped = exportFailure(error);
    if (mapped) return mapped;
    return error.message || "O pedido falhou.";
  }
  if (error instanceof Error && error.message) return error.message;
  return "Ocorreu um erro inesperado.";
}
