import { useState, type FormEvent } from "react";
import { useApi } from "../api/context";
import { messageOf } from "../lib/messages";
import { useTitle } from "../lib/useTitle";
import type { Passage, SourceLines } from "../types";

export function SearchPage() {
  const api = useApi();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Passage[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState("");
  const [passage, setPassage] = useState<SourceLines | null>(null);
  const [passageError, setPassageError] = useState("");
  useTitle("Pesquisa");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      setError("Escreva o que quer pesquisar no corpus.");
      setResults(null);
      setStatus("");
      return;
    }
    setBusy(true);
    setError("");
    setPassage(null);
    setPassageError("");
    setOpenId("");
    try {
      const items = await api.search(trimmed, 8);
      setResults(items);
      setStatus(items.length === 1 ? "1 resultado." : `${items.length} resultados.`);
    } catch (searchError) {
      setResults(null);
      setStatus("");
      setError(messageOf(searchError));
    } finally {
      setBusy(false);
    }
  }

  async function openPassage(item: Passage) {
    const key = `${item.document_id}:${item.line_start}:${item.line_end}`;
    setOpenId(key);
    setPassage(null);
    setPassageError("");
    try {
      const lines = await api.sourceLines(item.document_id, item.line_start, item.line_end);
      setPassage(lines);
    } catch (loadError) {
      setPassageError(messageOf(loadError));
    }
  }

  return (
    <>
      <p className="eyebrow">Corpus</p>
      <h1>Pesquisa</h1>
      <p className="lede">Pesquisa nas fontes publicadas do corpus. Os casos privados não entram neste índice.</p>
      <form className="search-form" role="search" onSubmit={onSubmit}>
        <label htmlFor="q">Pesquisar no corpus</label>
        <div className="search-row">
          <input
            id="q"
            name="q"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <button type="submit" disabled={busy}>
            {busy ? "A pesquisar…" : "Pesquisar"}
          </button>
        </div>
      </form>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      <p role="status" aria-live="polite" className="hint">
        {status}
      </p>
      {results && results.length === 0 && <p>Sem resultados.</p>}
      {results && results.length > 0 && (
        <ol className="results">
          {results.map((item) => {
            const key = `${item.document_id}:${item.line_start}:${item.line_end}`;
            const snippet = item.text.length > 320 ? `${item.text.slice(0, 320)}…` : item.text;
            return (
              <li key={key}>
                <article className="panel result">
                  <h2>{item.title}</h2>
                  <p className="hint">
                    linhas {item.line_start}–{item.line_end}
                  </p>
                  <p>{snippet}</p>
                  <button type="button" className="secondary" onClick={() => void openPassage(item)}>
                    Abrir passagem
                  </button>
                  {openId === key && passageError && (
                    <p role="alert" className="alert">
                      {passageError}
                    </p>
                  )}
                  {openId === key && passage && (
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
              </li>
            );
          })}
        </ol>
      )}
    </>
  );
}
