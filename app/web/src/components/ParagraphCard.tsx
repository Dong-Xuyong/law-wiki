import { useState, type FormEvent, type KeyboardEvent } from "react";
import { useApi } from "../api/context";
import { focusEvidence } from "./EvidencePanel";
import { confidenceLabel, reviewLabel } from "../lib/labels";
import { messageOf } from "../lib/messages";
import { parsePinpoint } from "../lib/pinpoint";
import { formatWhen } from "../lib/format";
import type { EvidenceItem, ReviewParagraph, Source, SourceLines } from "../types";

type ParagraphCardProps = {
  paragraph: ReviewParagraph;
  sources: Source[];
  evidence: EvidenceItem[];
  busy: boolean;
  onReview: (action: "accept" | "edit" | "reject", text?: string) => Promise<boolean>;
};

export function ParagraphCard({
  paragraph,
  sources,
  evidence,
  busy,
  onReview,
}: ParagraphCardProps) {
  const api = useApi();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(paragraph.text);
  const [passage, setPassage] = useState<SourceLines | null>(null);
  const [passageError, setPassageError] = useState("");
  const [loadingPin, setLoadingPin] = useState("");

  const citedEvidence = paragraph.evidenceIds
    .map((id) => evidence.find((item) => item.id === id))
    .filter((item): item is EvidenceItem => Boolean(item));

  async function openPin(source: Source, pinpoint: string) {
    const range = parsePinpoint(pinpoint);
    if (!range) {
      setPassage(null);
      setPassageError("Não foi possível ler o intervalo de linhas.");
      return;
    }
    setLoadingPin(`${source.id}:${pinpoint}`);
    setPassageError("");
    try {
      const lines = await api.sourceLines(source.document_id, range.start, range.end);
      setPassage(lines);
    } catch (error) {
      setPassage(null);
      setPassageError(messageOf(error));
    } finally {
      setLoadingPin("");
    }
  }

  async function save(event?: FormEvent) {
    event?.preventDefault();
    if (!text.trim() || busy) return;
    const ok = await onReview("edit", text);
    if (ok) setEditing(false);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      setText(paragraph.text);
      setEditing(false);
    }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void save();
    }
  }

  const rejected = paragraph.review.status === "rejected";

  return (
    <article
      className={rejected ? "para is-rejected" : "para"}
      data-confidence={paragraph.confidence}
      aria-busy={busy}
    >
      <header className="para-head">
        <h3>Parágrafo {paragraph.index + 1}</h3>
        <span className={`badge confidence-${paragraph.confidence}`}>
          <span className="visually-hidden">Confiança </span>
          {confidenceLabel(paragraph.confidence)}
        </span>
        <span className={`badge review-${paragraph.review.status}`}>
          <span className="visually-hidden">Revisão </span>
          {reviewLabel(paragraph.review.status)}
        </span>
      </header>
      {paragraph.note && <p className="para-note">{paragraph.note}</p>}
      {editing ? (
        <form onSubmit={save}>
          <label htmlFor={`edit-${paragraph.id}`}>Texto revisto</label>
          <textarea
            id={`edit-${paragraph.id}`}
            value={text}
            rows={6}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
          />
          <div className="actions">
            <button type="submit" disabled={busy || !text.trim()}>
              Guardar
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => {
                setText(paragraph.text);
                setEditing(false);
              }}
            >
              Cancelar
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="para-text">{paragraph.text}</p>
          {paragraph.review.status === "edited" && paragraph.text !== paragraph.originalText && (
            <details>
              <summary>Texto original</summary>
              <p className="para-text">{paragraph.originalText}</p>
            </details>
          )}
          {paragraph.review.status !== "pending" && paragraph.review.at && (
            <p className="hint">{formatWhen(paragraph.review.at)}</p>
          )}
          <div className="actions" role="group" aria-label={`Revisão do parágrafo ${paragraph.index + 1}`}>
            <button type="button" disabled={busy} onClick={() => void onReview("accept")}>
              Aceitar
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                setText(paragraph.text);
                setEditing(true);
              }}
            >
              Editar
            </button>
            <button type="button" className="danger" disabled={busy} onClick={() => void onReview("reject")}>
              Rejeitar
            </button>
          </div>
        </>
      )}
      {paragraph.sourceIds.length > 0 && (
        <div className="chip-row">
          <span className="chip-label">Fontes</span>
          {paragraph.sourceIds.map((sourceId) => {
            const source = sources.find((item) => item.id === sourceId);
            if (!source) {
              return (
                <span key={sourceId} className="chip chip-static">
                  {sourceId}
                </span>
              );
            }
            const pins = source.pinpoints.length > 0 ? source.pinpoints : [];
            if (pins.length === 0) {
              return (
                <span key={sourceId} className="chip chip-static">
                  {source.title}
                </span>
              );
            }
            return pins.map((pinpoint) => (
              <button
                key={`${sourceId}-${pinpoint}`}
                type="button"
                className="chip"
                aria-label={`Abrir ${source.title}, ${pinpoint}`}
                onClick={() => void openPin(source, pinpoint)}
              >
                {source.title} · {pinpoint}
              </button>
            ));
          })}
        </div>
      )}
      {citedEvidence.length > 0 && (
        <div className="chip-row">
          <span className="chip-label">Prova</span>
          {citedEvidence.map((item) => (
            <button
              key={item.id}
              type="button"
              className="chip"
              aria-label={`${item.id}: ${item.proposition}`}
              onClick={() => focusEvidence(item.id)}
            >
              {item.id}
            </button>
          ))}
        </div>
      )}
      {loadingPin && (
        <p role="status" className="hint">
          A carregar a passagem…
        </p>
      )}
      {passageError && (
        <p role="alert" className="alert">
          {passageError}
        </p>
      )}
      {passage && (
        <figure className="passage">
          <figcaption>
            {passage.title}, linhas {passage.lineStart}–{passage.lineEnd}
          </figcaption>
          <blockquote>{passage.text}</blockquote>
          <a href={passage.publicUrl} target="_blank" rel="noopener noreferrer">
            Abrir documento público
          </a>
        </figure>
      )}
    </article>
  );
}
