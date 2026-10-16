import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useApi } from "../api/context";
import { caseStatusLabel, draftStatusLabel, inputKindLabel } from "../lib/labels";
import { formatWhen } from "../lib/format";
import { messageOf } from "../lib/messages";
import { useTitle } from "../lib/useTitle";
import type { Case, DraftSummary } from "../types";

export function CasePage() {
  const { caseId = "" } = useParams();
  const location = useLocation();
  const api = useApi();
  const notice =
    location.state && typeof location.state === "object" && "notice" in location.state
      ? String((location.state as { notice?: unknown }).notice ?? "")
      : "";
  const [data, setData] = useState<{ case: Case; drafts: DraftSummary[] } | null>(null);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [failures, setFailures] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  useTitle(data?.case.title ?? "Caso");

  useEffect(() => {
    let stop = false;
    let timer = 0;
    const load = async () => {
      try {
        const next = await api.getCase(caseId);
        if (stop) return;
        setData(next);
        setError("");
        const active = next.drafts.some(
          (draft) => draft.status === "queued" || draft.status === "running",
        );
        if (active) timer = window.setTimeout(() => void load(), 5000);
      } catch (loadError) {
        if (!stop) setError(messageOf(loadError));
      }
    };
    void load();
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [api, caseId, tick]);

  useEffect(() => {
    if (!data) return;
    let stop = false;
    for (const draft of data.drafts) {
      if (draft.status !== "failed" || failures[draft.draftId]) continue;
      void api
        .getDraft(draft.draftId)
        .then((full) => {
          if (stop) return;
          setFailures((current) => ({
            ...current,
            [draft.draftId]: full.error || "A geração falhou.",
          }));
        })
        .catch(() => {
          if (stop) return;
          setFailures((current) => ({
            ...current,
            [draft.draftId]: "A geração falhou.",
          }));
        });
    }
    return () => {
      stop = true;
    };
  }, [api, data, failures]);

  async function generate() {
    setBusy(true);
    setActionError("");
    try {
      await api.createDraft(caseId);
      setTick((value) => value + 1);
    } catch (generateError) {
      setActionError(messageOf(generateError));
    } finally {
      setBusy(false);
    }
  }

  const active = data?.drafts.some((draft) => draft.status === "queued" || draft.status === "running");
  const live = active
    ? data?.drafts.some((draft) => draft.status === "running")
      ? "A gerar a minuta. Atualização automática a cada 5 segundos."
      : "Minuta em fila. Atualização automática a cada 5 segundos."
    : "";

  return (
    <>
      <p className="eyebrow">
        <Link to="/">Casos</Link>
      </p>
      {!data && !error && <p role="status">A carregar o caso…</p>}
      {notice && (
        <p role="status" className="alert">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {actionError && (
        <p role="alert" className="alert">
          {actionError}
        </p>
      )}
      {data && (
        <>
          <h1>{data.case.title}</h1>
          <dl className="meta-grid">
            <div>
              <dt>Estado</dt>
              <dd>{caseStatusLabel(data.case.status)}</dd>
            </div>
            <div>
              <dt>Origem</dt>
              <dd>{inputKindLabel(data.case.inputKind)}</dd>
            </div>
            <div>
              <dt>Criado</dt>
              <dd>{formatWhen(data.case.createdAt)}</dd>
            </div>
            <div>
              <dt>Atualizado</dt>
              <dd>{formatWhen(data.case.updatedAt)}</dd>
            </div>
          </dl>
          {data.case.status === "new" && (
            <p className="hint">
              Este caso ainda está marcado como novo. Se o PDF acabou de ser carregado, confirme que ficou pronto antes de gerar.
            </p>
          )}
          <div className="actions">
            <button type="button" onClick={() => void generate()} disabled={busy}>
              {busy ? "A pedir minuta…" : "Gerar minuta"}
            </button>
          </div>
          <p role="status" aria-live="polite" className="hint">
            {live}
          </p>
          <section aria-labelledby="minutas-titulo">
            <h2 id="minutas-titulo">Minutas</h2>
            {data.drafts.length === 0 && <p>Ainda não há minutas. Gere a primeira quando o caso estiver pronto.</p>}
            {data.drafts.length > 0 && (
              <ul className="case-list">
                {data.drafts.map((draft) => (
                  <li key={draft.draftId}>
                    <article className="panel case-card">
                      <h3>
                        <Link to={`/minutas/${draft.draftId}`}>Minuta {draft.draftId}</Link>
                      </h3>
                      <p className="hint">
                        <span className={`badge status-${draft.status}`}>{draftStatusLabel(draft.status)}</span>{" "}
                        {formatWhen(draft.createdAt)}
                      </p>
                      {draft.status === "failed" && (
                        <p role="alert" className="alert">
                          {failures[draft.draftId] || "A geração falhou."}
                        </p>
                      )}
                    </article>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </>
  );
}
