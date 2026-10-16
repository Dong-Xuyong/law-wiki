import { basisLabel, evidenceStatusLabel } from "../lib/labels";
import { formatEuro } from "../lib/format";
import type { Amount, EvidenceItem } from "../types";

const GROUPS = ["proved", "procedural", "not_proved"] as const;

export function focusEvidence(id: string): void {
  const element = document.getElementById(`evidence-${id}`);
  if (!element) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  element.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
  element.classList.add("is-target");
  window.setTimeout(() => element.classList.remove("is-target"), 1600);
}

export function EvidencePanel({
  evidence,
  amounts,
  decisionTotal,
}: {
  evidence: EvidenceItem[];
  amounts: Amount[];
  decisionTotal: string;
}) {
  return (
    <aside className="side" aria-label="Prova e montantes">
      <section className="panel">
        <h2>Matriz de prova</h2>
        {GROUPS.map((status) => {
          const items = evidence.filter((item) => item.status === status);
          return (
            <div key={status} className="evidence-group">
              <h3>{evidenceStatusLabel(status)}</h3>
              {items.length === 0 ? (
                <p className="hint">Nenhuma proposição.</p>
              ) : (
                <ul className="evidence-list">
                  {items.map((item) => (
                    <li key={item.id} id={`evidence-${item.id}`}>
                      <p>{item.proposition}</p>
                      <p className="hint">
                        <span className="badge">{item.id}</span> Base: {basisLabel(item.basis)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </section>
      <section className="panel">
        <h2>Montantes</h2>
        {amounts.length === 0 ? (
          <p className="hint">Sem montantes.</p>
        ) : (
          <div className="table-wrap">
            <table className="amounts">
              <caption className="visually-hidden">Pedido, concedido e razão de cada rubrica</caption>
              <thead>
                <tr>
                  <th scope="col">Rubrica</th>
                  <th scope="col" className="num">
                    Pedido
                  </th>
                  <th scope="col" className="num">
                    Concedido
                  </th>
                  <th scope="col">Razão</th>
                </tr>
              </thead>
              <tbody>
                {amounts.map((amount) => (
                  <tr key={amount.item}>
                    <th scope="row">{amount.item}</th>
                    <td className="num">{formatEuro(amount.claimed)}</td>
                    <td className="num">{formatEuro(amount.awarded)}</td>
                    <td>{amount.reason}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row">Total</th>
                  <td />
                  <td className="num">{formatEuro(decisionTotal)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>
    </aside>
  );
}
