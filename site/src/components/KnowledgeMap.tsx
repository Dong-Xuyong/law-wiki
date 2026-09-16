import { useEffect, useRef, useState } from "react";
import cytoscape from "cytoscape";

type GraphNode = { id: string; label: string; type: string; documentId?: string };
type GraphEdge = { source: string; target: string; predicate: string };
type Document = {
  id: string;
  title?: string;
  filename?: string;
  website?: string;
  topic_raw?: string;
  topic?: string;
  folder?: string;
  year?: string;
};

export default function KnowledgeMap({ base }: { base: string }) {
  const host = useRef<HTMLDivElement>(null);
  const instance = useRef<cytoscape.Core | null>(null);
  const payload = useRef<{ nodes: GraphNode[]; edges: GraphEdge[]; documents: Document[] } | null>(null);
  const [status, setStatus] = useState("A carregar o mapa…");
  const [query, setQuery] = useState("");

  const layout = (name: "cose" | "concentric") => {
    instance.current?.layout(
      name === "cose"
        ? { name: "cose", animate: false, fit: true, padding: 35, nodeRepulsion: () => 52000 }
        : { name: "concentric", animate: false, fit: true, padding: 35, minNodeSpacing: 42 },
    ).run();
  };

  const addDocument = (documentId: string) => {
    const cy = instance.current;
    const data = payload.current;
    if (!cy || !data) return;
    const record = data.documents.find((item) => item.id === documentId);
    if (!record) return;
    const id = `document:${documentId}`;
    if (cy.getElementById(id).empty()) {
      cy.add({ data: { id, label: record.title || record.filename || documentId, type: "document", documentId } });
    }
    for (const edge of data.edges.filter((item) => item.source === id || item.target === id)) {
      const other = edge.source === id ? edge.target : edge.source;
      const known = data.nodes.find((node) => node.id === other);
      if (known && cy.getElementById(other).empty()) cy.add({ data: known });
      const edgeId = `${edge.source}|${edge.predicate}|${edge.target}`;
      if (!cy.getElementById(edgeId).empty()) continue;
      if (!cy.getElementById(edge.source).empty() && !cy.getElementById(edge.target).empty()) {
        cy.add({ data: { id: edgeId, ...edge } });
      }
    }
  };

  const expandHub = (hubId: string) => {
    const data = payload.current;
    if (!data) return;
    const matches = data.edges
      .filter((edge) => edge.source === hubId && edge.target.startsWith("document:"))
      .slice(0, 120);
    for (const edge of matches) addDocument(edge.target.replace("document:", ""));
    setStatus(
      matches.length
        ? `${matches.length} documento(s) adicionados. Duplo clique num documento para o abrir.`
        : "Este nó não tem documentos adicionais no catálogo.",
    );
    layout("cose");
  };

  useEffect(() => {
    if (!host.current) return;
    Promise.all([
      fetch(`${base}/data/graph.json`).then((response) => response.json()),
      fetch(`${base}/data/catalog.json`).then((response) => response.json()),
    ]).then(([graph, catalog]) => {
      payload.current = { ...graph, documents: catalog.documents };
      const initialNodes = graph.nodes.filter((node: GraphNode) =>
        ["root", "group", "website", "topic", "folder", "instrument", "case"].includes(node.type),
      );
      const initialIds = new Set(initialNodes.map((node: GraphNode) => node.id));
      const initialEdges = graph.edges.filter((edge: GraphEdge) =>
        initialIds.has(edge.source) && initialIds.has(edge.target),
      );
      const cy = cytoscape({
        container: host.current,
        elements: [
          ...initialNodes.map((data: GraphNode) => ({ data })),
          ...initialEdges.map((edge: GraphEdge) => ({
            data: { id: `${edge.source}|${edge.predicate}|${edge.target}`, ...edge },
          })),
        ],
        style: [
          {
            selector: "node",
            style: {
              "background-color": "#0b3b36",
              color: "#17201f",
              label: "data(label)",
              "font-family": "DM Sans, sans-serif",
              "font-size": 10,
              "text-wrap": "ellipsis",
              "text-max-width": 120,
              "text-valign": "bottom",
              "text-margin-y": 7,
              width: 22,
              height: 22,
            },
          },
          { selector: 'node[type = "instrument"]', style: { "background-color": "#b7802b", width: 30, height: 30 } },
          { selector: 'node[type = "case"]', style: { "background-color": "#6c5285", width: 30, height: 30 } },
          { selector: 'node[type = "root"]', style: { "background-color": "#8c3c32", width: 48, height: 48, "font-size": 13 } },
          { selector: 'node[type = "group"]', style: { "background-color": "#b7802b", width: 36, height: 36, "font-size": 12 } },
          { selector: 'node[type = "document"]', style: { "background-color": "#2c6e9b", width: 16, height: 16 } },
          { selector: "edge", style: { width: 1, "line-color": "#aebbb7", "curve-style": "bezier", opacity: 0.65 } },
          { selector: ":selected", style: { "border-width": 4, "border-color": "#d5a44f" } },
        ],
      });
      instance.current = cy;
      cy.on("tap", "node", (event) => {
        const node = event.target;
        const type = node.data("type");
        if (type === "document") {
          window.location.href = `${base}/documents/${node.data("documentId")}/`;
          return;
        }
        setStatus(`${node.data("label")} · ${type}. A expandir documentos relacionados.`);
        expandHub(node.id());
      });
      const requested = new URLSearchParams(window.location.search).get("document");
      if (requested) addDocument(requested);
      layout("concentric");
      setStatus("Selecione um tema, fonte ou pasta para revelar documentos relacionados.");
    }).catch((error) => {
      console.error(error);
      setStatus("Não foi possível carregar os dados do mapa.");
    });
    return () => instance.current?.destroy();
  }, [base]);

  const findNodes = () => {
    const cy = instance.current;
    const data = payload.current;
    if (!cy || !data || !query.trim()) return;
    const needle = query.trim().toLocaleLowerCase("pt");
    const hub = data.nodes.find((node) => node.label.toLocaleLowerCase("pt").includes(needle));
    if (hub) {
      if (cy.getElementById(hub.id).empty()) cy.add({ data: hub });
      cy.getElementById(hub.id).select();
      cy.animate({ center: { eles: cy.getElementById(hub.id) }, zoom: 1.5 }, { duration: 250 });
      setStatus(`Nó encontrado: ${hub.label}.`);
      return;
    }
    const docs = data.documents.filter((doc) =>
      `${doc.title} ${doc.filename}`.toLocaleLowerCase("pt").includes(needle),
    ).slice(0, 25);
    docs.forEach((doc) => addDocument(doc.id));
    layout("cose");
    setStatus(docs.length ? `${docs.length} documento(s) adicionados ao mapa.` : "Nenhum nó encontrado.");
  };

  return (
    <>
      <div className="map-controls">
        <input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => event.key === "Enter" && findNodes()} placeholder="Localizar tema, fonte ou documento…" />
        <button onClick={findNodes}>Localizar</button>
        <button className="secondary" onClick={() => layout("concentric")}>Mapa mental</button>
        <button className="secondary" onClick={() => layout("cose")}>Rede</button>
      </div>
      <p className="map-note">{status}</p>
      <div className="panel map-shell"><div id="cy" ref={host}></div></div>
    </>
  );
}
