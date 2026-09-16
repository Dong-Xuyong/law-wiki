import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape from "cytoscape";

type GraphNode = {
  id: string;
  label: string;
  type: string;
  documentId?: string;
  count?: number;
};
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
type Keyword = {
  key: string;
  label: string;
  type: string;
  count: number;
  documents: string[];
  nodeIds: string[];
};
type Payload = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  keywords: Keyword[];
  documents: Document[];
};
type View =
  | { kind: "root"; offset: number }
  | { kind: "group"; focusId: string; offset: number }
  | { kind: "hub"; focusId: string; offset: number }
  | { kind: "keyword"; keys: string[]; offset: number }
  | { kind: "search"; query: string; offset: number };
type LayoutName = "hierarchy" | "radial" | "network";

const PAGE_SIZE = 14;
const ROOT_ID = "root:law-wiki";
const LEGAL_TYPES = new Set(["instrument", "case", "concept", "entity", "forum", "authority"]);

export default function KnowledgeMap({ base }: { base: string }) {
  const host = useRef<HTMLDivElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const instance = useRef<cytoscape.Core | null>(null);
  const payload = useRef<Payload | null>(null);
  const currentView = useRef<View>({ kind: "root", offset: PAGE_SIZE });
  const history = useRef<View[]>([]);
  const layoutName = useRef<LayoutName>("hierarchy");
  const [status, setStatus] = useState("A carregar o mapa…");
  const [query, setQuery] = useState("");
  const [keywordQuery, setKeywordQuery] = useState("");
  const [activeKeywords, setActiveKeywords] = useState<string[]>([]);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [canGoBack, setCanGoBack] = useState(false);
  const [canShowMore, setCanShowMore] = useState(false);
  const [visibleCount, setVisibleCount] = useState(0);

  const nodeById = (id: string) => payload.current?.nodes.find((node) => node.id === id);
  const documentById = (id: string) => payload.current?.documents.find((document) => document.id === id);
  const documentNode = (id: string): GraphNode => {
    const document = documentById(id);
    return {
      id: `document:${id}`,
      label: document?.title || document?.filename || id,
      type: "document",
      documentId: id,
      count: 1,
    };
  };

  const uniqueNodes = (nodes: GraphNode[]) =>
    [...new Map(nodes.filter(Boolean).map((node) => [node.id, node])).values()];
  const uniqueEdges = (edges: GraphEdge[]) =>
    [...new Map(edges.map((edge) => [`${edge.source}|${edge.predicate}|${edge.target}`, edge])).values()];

  const runLayout = (name: LayoutName = layoutName.current) => {
    const cy = instance.current;
    if (!cy) return;
    layoutName.current = name;
    const options =
      name === "network"
        ? { name: "cose", animate: false, fit: false, padding: 65, nodeRepulsion: () => 90000, idealEdgeLength: () => 130 }
        : name === "radial"
          ? { name: "concentric", animate: false, fit: false, padding: 65, minNodeSpacing: 90, levelWidth: () => 1 }
          : { name: "breadthfirst", directed: true, circle: false, animate: false, fit: false, padding: 65, spacingFactor: 1.45 };
    cy.layout(options as cytoscape.LayoutOptions).run();
    requestAnimationFrame(() => cy.fit(cy.elements(), 75));
  };

  const replaceGraph = (nodes: GraphNode[], edges: GraphEdge[], message: string) => {
    const cy = instance.current;
    if (!cy) return;
    const renderedNodes = uniqueNodes(nodes);
    const nodeIds = new Set(renderedNodes.map((node) => node.id));
    const renderedEdges = uniqueEdges(edges).filter(
      (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target),
    );
    cy.elements().remove();
    cy.add([
      ...renderedNodes.map((data) => ({ data })),
      ...renderedEdges.map((edge) => ({
        data: { id: `${edge.source}|${edge.predicate}|${edge.target}`, ...edge },
      })),
    ]);
    setSelected(null);
    setVisibleCount(renderedNodes.length);
    setStatus(message);
    runLayout();
  };

  const documentIdsForHub = (hubId: string) => {
    const data = payload.current;
    if (!data) return [];
    const ids = new Set<string>();
    for (const edge of data.edges) {
      if (edge.source === hubId && edge.target.startsWith("document:")) {
        ids.add(edge.target.replace("document:", ""));
      }
      if (edge.target === hubId && edge.source.startsWith("document:")) {
        ids.add(edge.source.replace("document:", ""));
      }
    }
    return [...ids].sort((a, b) =>
      (documentById(a)?.title || a).localeCompare(documentById(b)?.title || b, "pt"),
    );
  };

  const legalNeighbors = (documentIds: string[]) => {
    const data = payload.current;
    if (!data) return { nodes: [] as GraphNode[], edges: [] as GraphEdge[] };
    const documentKeys = new Set(documentIds.map((id) => `document:${id}`));
    const edges = data.edges.filter(
      (edge) =>
        !["website", "topic", "folder", "contains"].includes(edge.predicate)
        && (documentKeys.has(edge.source) || documentKeys.has(edge.target)),
    );
    const neighborIds = new Set(
      edges.flatMap((edge) => [edge.source, edge.target]).filter((id) => !documentKeys.has(id)),
    );
    return {
      nodes: [...neighborIds].map((id) => nodeById(id)).filter((node): node is GraphNode => Boolean(node)),
      edges,
    };
  };

  const renderView = (view: View) => {
    const data = payload.current;
    if (!data) return;
    currentView.current = view;
    setCanGoBack(history.current.length > 0);

    if (view.kind === "root") {
      const root = nodeById(ROOT_ID)!;
      const groups = data.nodes.filter((node) => node.type === "group");
      const ids = new Set([ROOT_ID, ...groups.map((node) => node.id)]);
      const edges = data.edges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
      setCanShowMore(false);
      replaceGraph(
        [root, ...groups],
        edges,
        "Escolha uma categoria. O mapa abre apenas um ramo de cada vez para manter os rótulos legíveis.",
      );
      return;
    }

    if (view.kind === "group") {
      const group = nodeById(view.focusId);
      if (!group) return;
      const allHubIds = data.edges
        .filter((edge) => edge.source === view.focusId && edge.predicate === "contains")
        .map((edge) => edge.target);
      const hubs = allHubIds.slice(0, view.offset)
        .map((id) => nodeById(id))
        .filter((node): node is GraphNode => Boolean(node));
      const root = nodeById(ROOT_ID)!;
      const nodes = [root, group, ...hubs];
      const ids = new Set(nodes.map((node) => node.id));
      const edges = data.edges.filter(
        (edge) => edge.predicate === "contains" && ids.has(edge.source) && ids.has(edge.target),
      );
      setCanShowMore(view.offset < allHubIds.length);
      replaceGraph(
        nodes,
        edges,
        `${group.label}: ${Math.min(view.offset, allHubIds.length)} de ${allHubIds.length} ramo(s).`,
      );
      return;
    }

    if (view.kind === "hub") {
      const hub = nodeById(view.focusId);
      if (!hub) return;
      const allDocuments = documentIdsForHub(view.focusId);
      const shown = allDocuments.slice(0, view.offset);
      const parentEdge = data.edges.find(
        (edge) => edge.target === view.focusId && edge.predicate === "contains",
      );
      const parent = parentEdge ? nodeById(parentEdge.source) : undefined;
      const documents = shown.map(documentNode);
      const relationData = legalNeighbors(shown);
      const nodes = [...(parent ? [parent] : []), hub, ...documents, ...relationData.nodes];
      const edges: GraphEdge[] = [
        ...(parent ? [{ source: parent.id, target: hub.id, predicate: "contains" }] : []),
        ...shown.map((id) => ({
          source: hub.id,
          target: `document:${id}`,
          predicate: hub.type,
        })),
        ...relationData.edges,
      ];
      setCanShowMore(view.offset < allDocuments.length);
      replaceGraph(
        nodes,
        edges,
        `${hub.label}: ${Math.min(view.offset, allDocuments.length)} de ${allDocuments.length} documento(s).`,
      );
      return;
    }

    if (view.kind === "keyword") {
      const selectedKeywords = view.keys
        .map((key) => data.keywords.find((keyword) => keyword.key === key))
        .filter((keyword): keyword is Keyword => Boolean(keyword));
      if (!selectedKeywords.length) {
        renderView({ kind: "root", offset: PAGE_SIZE });
        return;
      }
      const matches = selectedKeywords
        .map((keyword) => new Set(keyword.documents))
        .reduce((current, next) => new Set([...current].filter((id) => next.has(id))));
      const allDocuments = [...matches].sort((a, b) =>
        (documentById(a)?.title || a).localeCompare(documentById(b)?.title || b, "pt"),
      );
      const shown = allDocuments.slice(0, view.offset);
      const keywordNodes = selectedKeywords.map((keyword) => ({
        id: `filter:${keyword.key}`,
        label: keyword.label,
        type: "keyword",
        count: keyword.count,
      }));
      const documents = shown.map(documentNode);
      const edges = keywordNodes.flatMap((keywordNode, index) =>
        shown
          .filter((id) => selectedKeywords[index].documents.includes(id))
          .map((id) => ({ source: keywordNode.id, target: `document:${id}`, predicate: "keyword" })),
      );
      setCanShowMore(view.offset < allDocuments.length);
      replaceGraph(
        [...keywordNodes, ...documents],
        edges,
        `${allDocuments.length} documento(s) correspondem a ${selectedKeywords.length} palavra(s)-chave.`,
      );
      return;
    }

    const needle = view.query.toLocaleLowerCase("pt");
    const matchingNodes = data.nodes
      .filter((node) => node.label.toLocaleLowerCase("pt").includes(needle))
      .slice(0, view.offset);
    const matchingDocuments = data.documents
      .filter((document) => `${document.title} ${document.filename}`.toLocaleLowerCase("pt").includes(needle))
      .slice(0, view.offset);
    const searchRoot: GraphNode = { id: "search:results", label: `Pesquisa: ${view.query}`, type: "keyword", count: matchingNodes.length + matchingDocuments.length };
    const documents = matchingDocuments.map((document) => documentNode(document.id));
    const nodes = [searchRoot, ...matchingNodes, ...documents];
    const edges = nodes.slice(1).map((node) => ({ source: searchRoot.id, target: node.id, predicate: "search" }));
    setCanShowMore(false);
    replaceGraph(nodes, edges, `${nodes.length - 1} resultado(s) visíveis para “${view.query}”.`);
  };

  const navigate = (view: View, remember = true) => {
    if (remember) history.current.push(currentView.current);
    renderView(view);
  };

  const updateKeywordUrl = (keys: string[]) => {
    const url = new URL(window.location.href);
    url.searchParams.delete("keyword");
    url.searchParams.delete("document");
    keys.forEach((key) => url.searchParams.append("keyword", key));
    window.history.replaceState({}, "", url);
  };

  const applyKeywords = (keys: string[]) => {
    const unique = [...new Set(keys)];
    setActiveKeywords(unique);
    updateKeywordUrl(unique);
    if (unique.length) {
      navigate({ kind: "keyword", keys: unique, offset: PAGE_SIZE });
    } else {
      history.current = [];
      renderView({ kind: "root", offset: PAGE_SIZE });
    }
  };

  useEffect(() => {
    if (!host.current) return;
    Promise.all([
      fetch(`${base}/data/graph.json`).then((response) => response.json()),
      fetch(`${base}/data/catalog.json`).then((response) => response.json()),
    ]).then(([graph, catalog]) => {
      payload.current = { ...graph, keywords: graph.keywords || [], documents: catalog.documents };
      const cy = cytoscape({
        container: host.current,
        minZoom: 0.35,
        maxZoom: 3.5,
        wheelSensitivity: 0.18,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "#0b3b36",
              color: "#17201f",
              label: "data(label)",
              "font-family": "DM Sans, sans-serif",
              "font-size": 14,
              "font-weight": 600,
              "text-wrap": "wrap",
              "text-max-width": "165px",
              "text-valign": "bottom",
              "text-margin-y": 9,
              "text-background-color": "#fffef9",
              "text-background-opacity": 0.93,
              "text-background-padding": "4px",
              width: 30,
              height: 30,
            },
          },
          { selector: 'node[type = "root"]', style: { "background-color": "#8c3c32", width: 70, height: 70, "font-size": 18, "text-max-width": "210px" } },
          { selector: 'node[type = "group"]', style: { "background-color": "#b7802b", width: 56, height: 56, "font-size": 17, "text-max-width": "200px" } },
          { selector: 'node[type = "instrument"], node[type = "case"]', style: { "background-color": "#6c5285", width: 40, height: 40 } },
          { selector: 'node[type = "keyword"]', style: { "background-color": "#b7802b", width: 54, height: 54, "font-size": 16 } },
          { selector: 'node[type = "document"]', style: { "background-color": "#2c6e9b", width: 26, height: 26, "font-size": 13, "text-max-width": "190px" } },
          { selector: "edge", style: { width: 1.7, "line-color": "#94a7a2", "curve-style": "bezier", opacity: 0.72 } },
          { selector: 'edge[predicate = "keyword"]', style: { "line-color": "#b7802b", width: 2.2 } },
          { selector: ":selected", style: { "border-width": 5, "border-color": "#d5a44f" } },
        ],
      });
      instance.current = cy;
      cy.on("tap", "node", (event) => {
        const node = event.target;
        const nodeData = node.data() as GraphNode;
        setSelected(nodeData);
        if (nodeData.type === "root") {
          history.current = [];
          renderView({ kind: "root", offset: PAGE_SIZE });
        } else if (nodeData.type === "group") {
          navigate({ kind: "group", focusId: nodeData.id, offset: PAGE_SIZE });
        } else if (["website", "topic", "folder"].includes(nodeData.type) || LEGAL_TYPES.has(nodeData.type)) {
          navigate({ kind: "hub", focusId: nodeData.id, offset: PAGE_SIZE });
        }
      });
      const requestedKeywords = new URLSearchParams(window.location.search).getAll("keyword");
      const requestedDocument = new URLSearchParams(window.location.search).get("document");
      if (requestedKeywords.length) {
        setActiveKeywords(requestedKeywords);
        renderView({ kind: "keyword", keys: requestedKeywords, offset: PAGE_SIZE });
      } else if (requestedDocument) {
        const record = documentById(requestedDocument);
        const root: GraphNode = { id: "document:focus", label: "Documento selecionado", type: "keyword", count: 1 };
        const doc = documentNode(requestedDocument);
        const relations = legalNeighbors([requestedDocument]);
        replaceGraph([root, doc, ...relations.nodes], [
          { source: root.id, target: doc.id, predicate: "focus" },
          ...relations.edges,
        ], record ? `Relações de ${record.title}.` : "Documento não encontrado.");
      } else {
        renderView({ kind: "root", offset: PAGE_SIZE });
      }
    }).catch((error) => {
      console.error(error);
      setStatus("Não foi possível carregar os dados do mapa.");
    });
    return () => instance.current?.destroy();
  }, [base]);

  const findNodes = () => {
    if (!query.trim()) return;
    setActiveKeywords([]);
    updateKeywordUrl([]);
    navigate({ kind: "search", query: query.trim(), offset: PAGE_SIZE });
  };
  const goBack = () => {
    const previous = history.current.pop();
    if (previous) {
      const keys = previous.kind === "keyword" ? previous.keys : [];
      setActiveKeywords(keys);
      updateKeywordUrl(keys);
      renderView(previous);
    }
  };
  const reset = () => {
    history.current = [];
    setActiveKeywords([]);
    setQuery("");
    updateKeywordUrl([]);
    renderView({ kind: "root", offset: PAGE_SIZE });
  };
  const showMore = () => {
    const view = currentView.current;
    renderView({ ...view, offset: view.offset + PAGE_SIZE } as View);
  };
  const toggleKeyword = (key: string) => {
    applyKeywords(
      activeKeywords.includes(key)
        ? activeKeywords.filter((item) => item !== key)
        : [...activeKeywords, key],
    );
  };
  const zoom = (factor: number) => {
    const cy = instance.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  };
  const fullscreen = async () => {
    if (!shell.current) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else await shell.current.requestFullscreen();
    setTimeout(() => {
      instance.current?.resize();
      instance.current?.fit(instance.current.elements(), 75);
    }, 100);
  };

  const displayedKeywords = useMemo(() => {
    const keywords = payload.current?.keywords || [];
    const needle = keywordQuery.trim().toLocaleLowerCase("pt");
    return keywords
      .filter((keyword) => !needle || keyword.label.toLocaleLowerCase("pt").includes(needle))
      .slice(0, needle ? 30 : 18);
  }, [keywordQuery, status]);

  return (
    <>
      <section className="keyword-panel" aria-label="Palavras-chave">
        <div className="keyword-heading">
          <div>
            <strong>Palavras-chave</strong>
            <span>Selecione para cruzar documentos e focar o mapa.</span>
          </div>
          <input
            value={keywordQuery}
            onChange={(event) => setKeywordQuery(event.target.value)}
            placeholder="Filtrar palavras-chave…"
            aria-label="Filtrar palavras-chave"
          />
        </div>
        <div className="keyword-chips">
          {displayedKeywords.map((keyword) => (
            <button
              key={keyword.key}
              className={`keyword-chip ${activeKeywords.includes(keyword.key) ? "active" : ""}`}
              onClick={() => toggleKeyword(keyword.key)}
              aria-pressed={activeKeywords.includes(keyword.key)}
            >
              {keyword.label}<span>{keyword.count}</span>
            </button>
          ))}
        </div>
        {activeKeywords.length > 0 && (
          <button className="keyword-clear" onClick={() => applyKeywords([])}>Limpar palavras-chave</button>
        )}
      </section>

      <div className="map-controls">
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && findNodes()}
          placeholder="Localizar tema, fonte ou documento…"
        />
        <button onClick={findNodes}>Localizar</button>
        <button className="secondary" onClick={goBack} disabled={!canGoBack}>Voltar</button>
        <button className="secondary" onClick={reset}>Início</button>
        {canShowMore && <button className="secondary" onClick={showMore}>Mostrar mais</button>}
      </div>
      <div className="map-view-controls" aria-label="Controlos de visualização">
        <button className="secondary" onClick={() => { layoutName.current = "hierarchy"; runLayout(); }}>Hierarquia</button>
        <button className="secondary" onClick={() => { layoutName.current = "radial"; runLayout(); }}>Radial</button>
        <button className="secondary" onClick={() => { layoutName.current = "network"; runLayout(); }}>Rede</button>
        <button className="secondary icon-button" onClick={() => zoom(1.25)} aria-label="Aumentar zoom">＋</button>
        <button className="secondary icon-button" onClick={() => zoom(0.8)} aria-label="Diminuir zoom">−</button>
        <button className="secondary" onClick={() => instance.current?.fit(instance.current.elements(), 75)}>Ajustar ramo</button>
        <button className="secondary" onClick={fullscreen}>Ecrã inteiro</button>
      </div>
      <p className="map-note">{status} <strong>{visibleCount}</strong> nós visíveis.</p>
      <div className="map-workspace">
        <div className="panel map-shell" ref={shell}><div id="cy" ref={host}></div></div>
        <aside className="panel node-details" aria-live="polite">
          {selected ? (
            <>
              <span className="eyebrow">{selected.type}</span>
              <h2>{selected.label}</h2>
              {typeof selected.count === "number" && <p>{selected.count.toLocaleString("pt-PT")} ligação(ões) catalogadas.</p>}
              {selected.type === "document" && selected.documentId && (
                <a className="button" href={`${base}/documents/${selected.documentId}/`}>Abrir documento</a>
              )}
              {LEGAL_TYPES.has(selected.type) && <p className="map-note">Relação proveniente do grafo jurídico aceite; a fonte mantém o seu estado de verificação.</p>}
            </>
          ) : (
            <>
              <span className="eyebrow">Navegação</span>
              <h2>Selecione um nó</h2>
              <p>Os detalhes surgem aqui sem reduzir o espaço do mapa. Arraste para deslocar e use a roda ou os botões para ampliar.</p>
            </>
          )}
        </aside>
      </div>
    </>
  );
}
