import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useApi } from "../api/context";
import { EvidencePanel } from "../components/EvidencePanel";
import { ParagraphCard } from "../components/ParagraphCard";
import { draftStatusLabel } from "../lib/labels";
import { groupParagraphs } from "../lib/group";
import { formatWhen } from "../lib/format";
import { messageOf } from "../lib/messages";
import { useTitle } from "../lib/useTitle";
import type { Draft, ReviewAction } from "../types";

export function DraftPage() {
  const { draftId = "" } = useParams();
  const api = useApi();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [caseTitle, setCaseTitle] = useState("");
  const [error, setError] = useState("");
  const [uncertainFirst, setUncertainFirst] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  useTitle(caseTitle || "Minuta");

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const load = async () => {
      try {
        const next = await api.getDraft(draftId);
        if (stop) return;
        setDraft(next);
        if (next.status === "queued" || next.status === "running") {
          timer = window.setTimeout(() => void load(), 5000);
        }
      } catch (loadError) {
        if (!stop) setError(messageOf(loadError));
      }
    };
    void load();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [api, draftId]);

  useEffect(() => {
    if (!draft?.caseId) return;
    let stop = false;
    void api
      .getCase(draft.caseId)
      .then((data) => {
        if (!stop) setCaseTitle(data.case.title);
      })
      .catch(() => undefined);
    return () => {
      stop = true;
    };
  }, [api, draft?.caseId]);

  async function review(paragraphId: string, action: ReviewAction, text?: string): Promise<boolean> {
    setBusyId(paragraphId);
    setError("");
    try {
      const body = action === "edit" ? { action, text } : { action };
      const updated = await api.reviewParagraph(draftId, paragraphId, body);
      setDraft((current) => {
        if (!current) return current;
        const paragraphs = current.paragraphs.map((paragraph) =>
          paragraph.id === updated.id ? updated : paragraph,
        );
        const reviewedCount = paragraphs.filter((paragraph) => paragraph.review.status !== "pending").length;
        return { ...current, paragraphs, reviewedCount, totalCount: paragraphs.length };
      });
      return true;
    } catch (reviewError) {
      setError(messageOf(reviewError));
      return false;
    } finally {
      setBusyId(null);
    }
  }

  async function onExport() {
    setExporting(true);
    setError("");
    try {
      const result = await api.exportDraft(draftId);
      window.location.assign(result.url);
      setExporting(false);
    } catch (exportError) {
      setError(messageOf(exportError));
      setExporting(false);
    }
  }

  if (!draft && !error) return <p role="status">A carregar a minuta…</p>;

  const waiting = draft?.status === "queued" || draft?.status === "running";
  const canExport = Boolean(
    draft && draft.status === "ready" && draft.totalCount > 0 && draft.reviewedCount === draft.totalCount,
  );
  const groups = draft ? groupParagraphs(draft.paragraphs, uncertainFirst) : [];

  return (
    <>
      <p className="eyebrow">
        {draft?.caseId ? <Link to={`/casos/${draft.caseId}`}>Voltar ao caso</Link> : <Link to="/">Casos</Link>}
      </p>
      <h1>{caseTitle || "Minuta"}</h1>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {draft && (
        <>
          <dl className="meta-grid">
            <div>
              <dt>Estado</dt>
              <dd>{draftStatusLabel(draft.status)}</dd>
            </div>
            <div>
              <dt>Criada</dt>
              <dd>{formatWhen(draft.createdAt)}</dd>
            </div>
            {draft.modelId && (
              <div>
                <dt>Modelo</dt>
                <dd>{draft.modelId}</dd>
              </div>
            )}
          </dl>
          {waiting && (
            <p role="status" aria-live="polite">
              {draft.status === "running"
                ? "A gerar a minuta. Atualização automática a cada 5 segundos."
                : "Minuta em fila. Atualização automática a cada 5 segundos."}
            </p>
          )}
          {draft.status === "failed" && (
            <p role="alert" className="alert">
              {draft.error || "A geração falhou."}
            </p>
          )}
          {draft.status === "ready" && (
            <>
              <div className="toolbar">
                <p id="progress-label" aria-live="polite">
                  {draft.reviewedCount} de {draft.totalCount} parágrafos revistos
                </p>
                <progress value={draft.reviewedCount} max={Math.max(draft.totalCount, 1)} />
                <button
                  type="button"
                  disabled={!canExport || exporting}
                  aria-describedby="export-hint"
                  onClick={() => void onExport()}
                >
                  {exporting ? "A exportar…" : "Exportar Word"}
                </button>
              </div>
              <p id="export-hint" className="hint">
                {canExport
                  ? "Todos os parágrafos foram revistos. Pode exportar o documento Word."
                  : "Reveja todos os parágrafos para exportar."}
              </p>
              <div className="minuta-grid">
                <div>
                  <div className="uncertain-toggle">
                    <input
                      id="uncertain-first"
                      type="checkbox"
                      checked={uncertainFirst}
                      onChange={(event) => setUncertainFirst(event.target.checked)}
                    />
                    <label htmlFor="uncertain-first">Mostrar primeiro os parágrafos incertos</label>
                  </div>
                  {groups.map((group) => (
                    <section key={group.section} className="section-block" aria-labelledby={`sec-${group.section}`}>
                      <h2 id={`sec-${group.section}`}>{group.label}</h2>
                      {group.items.map((paragraph) => (
                        <ParagraphCard
                          key={paragraph.id}
                          paragraph={paragraph}
                          sources={draft.sources}
                          evidence={draft.evidence}
                          busy={busyId === paragraph.id}
                          onReview={(action, text) => review(paragraph.id, action, text)}
                        />
                      ))}
                    </section>
                  ))}
                </div>
                <EvidencePanel
                  evidence={draft.evidence}
                  amounts={draft.amounts}
                  decisionTotal={draft.decisionTotal}
                />
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
