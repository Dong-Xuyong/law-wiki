import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useApi } from "../api/context";
import { ApiError } from "../api/errors";
import { caseStatusLabel, inputKindLabel } from "../lib/labels";
import { formatWhen } from "../lib/format";
import { messageOf } from "../lib/messages";
import { useTitle } from "../lib/useTitle";
import type { Case, InputKind } from "../types";

const MAX_PDF_BYTES = 15 * 1024 * 1024;

function isPdf(file: File): boolean {
  if (!file.name.toLowerCase().endsWith(".pdf")) return false;
  if (!file.type) return true;
  return file.type === "application/pdf" || file.type === "application/x-pdf";
}

export function CasesPage() {
  const api = useApi();
  const navigate = useNavigate();
  const [cases, setCases] = useState<Case[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<InputKind>("text");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fictional, setFictional] = useState(false);
  const [formError, setFormError] = useState("");
  const [busy, setBusy] = useState(false);
  useTitle("Casos");

  useEffect(() => {
    let stop = false;
    void api
      .listCases()
      .then((items) => {
        if (!stop) setCases(items);
      })
      .catch((error: unknown) => {
        if (!stop) setLoadError(messageOf(error));
      });
    return () => {
      stop = true;
    };
  }, [api]);

  function onFile(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0] ?? null;
    setFile(next);
    if (!next) return;
    if (!isPdf(next)) setFormError("O ficheiro tem de ser um PDF.");
    else if (next.size > MAX_PDF_BYTES) setFormError("O PDF não pode exceder 15 MB.");
    else setFormError("");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!fictional || busy) return;
    if (!title.trim()) {
      setFormError("Indique o título do caso.");
      return;
    }
    if (kind === "text" && !text.trim()) {
      setFormError("Cole o texto do caso.");
      return;
    }
    if (kind === "pdf") {
      if (!file) {
        setFormError("Selecione um ficheiro PDF.");
        return;
      }
      if (!isPdf(file)) {
        setFormError("O ficheiro tem de ser um PDF.");
        return;
      }
      if (file.size > MAX_PDF_BYTES) {
        setFormError("O PDF não pode exceder 15 MB.");
        return;
      }
    }
    setBusy(true);
    setFormError("");
    try {
      const created = await api.createCase(
        kind === "text"
          ? { title: title.trim(), text: text.trim(), inputKind: "text", fictional: true }
          : { title: title.trim(), inputKind: "pdf", fictional: true },
      );
      if (kind === "pdf" && file) {
        if (!created.uploadUrl) {
          throw new ApiError("O servidor não devolveu o endereço de carregamento.", 500, "upload_missing");
        }
        try {
          await api.uploadPdf(created.uploadUrl, file);
        } catch (error) {
          navigate(`/casos/${created.case.caseId}`, {
            state: {
              notice: `${messageOf(error)} O caso foi criado, mas o PDF não ficou carregado. O contrato não prevê um segundo carregamento.`,
            },
          });
          return;
        }
      }
      navigate(`/casos/${created.case.caseId}`);
    } catch (error) {
      setFormError(messageOf(error));
      setBusy(false);
    }
  }

  return (
    <>
      <p className="eyebrow">Casos</p>
      <h1>Casos fictícios</h1>
      <p className="lede">
        Crie um caso a partir de texto ou de um PDF e gere uma minuta para rever parágrafo a parágrafo.
      </p>

      <section className="panel form-panel" aria-labelledby="novo-caso">
        <h2 id="novo-caso">Novo caso</h2>
        <form onSubmit={onSubmit}>
          <label htmlFor="case-title">Título</label>
          <input
            id="case-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            required
            autoComplete="off"
          />
          <fieldset>
            <legend>Origem do caso</legend>
            <div className="choice">
              <label>
                <input
                  type="radio"
                  name="input-kind"
                  value="text"
                  checked={kind === "text"}
                  onChange={() => setKind("text")}
                />
                Colar texto
              </label>
              <label>
                <input
                  type="radio"
                  name="input-kind"
                  value="pdf"
                  checked={kind === "pdf"}
                  onChange={() => setKind("pdf")}
                />
                Carregar PDF
              </label>
            </div>
          </fieldset>
          {kind === "text" ? (
            <>
              <label htmlFor="case-text">Texto do caso</label>
              <textarea
                id="case-text"
                value={text}
                rows={10}
                required
                onChange={(event) => setText(event.target.value)}
              />
            </>
          ) : (
            <>
              <label htmlFor="case-pdf">Ficheiro PDF</label>
              <input
                id="case-pdf"
                type="file"
                accept="application/pdf,.pdf"
                required
                onChange={onFile}
              />
              <p className="hint">Apenas PDF, até 15 MB.</p>
            </>
          )}
          <label className="check">
            <input
              type="checkbox"
              checked={fictional}
              required
              onChange={(event) => setFictional(event.target.checked)}
            />
            <span>Confirmo que é um caso fictício ou uma decisão publicada</span>
          </label>
          {!fictional && <p className="hint">Marque a confirmação para poder criar o caso.</p>}
          {formError && (
            <p role="alert" className="alert">
              {formError}
            </p>
          )}
          <div className="actions">
            <button type="submit" disabled={!fictional || busy}>
              {busy ? "A criar…" : "Criar caso"}
            </button>
          </div>
        </form>
      </section>

      <section aria-labelledby="lista-casos">
        <h2 id="lista-casos">Casos</h2>
        {loadError && (
          <p role="alert" className="alert">
            {loadError}
          </p>
        )}
        {cases === null && !loadError && <p role="status">A carregar casos…</p>}
        {cases && cases.length === 0 && <p>Ainda não há casos.</p>}
        {cases && cases.length > 0 && (
          <ul className="case-list">
            {cases.map((item) => (
              <li key={item.caseId}>
                <article className="panel case-card">
                  <h3>
                    <Link to={`/casos/${item.caseId}`}>{item.title}</Link>
                  </h3>
                  <p className="hint">
                    {inputKindLabel(item.inputKind)} · {caseStatusLabel(item.status)} ·{" "}
                    {formatWhen(item.updatedAt)}
                  </p>
                </article>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
