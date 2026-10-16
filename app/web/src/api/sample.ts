import type {
  Amount,
  EvidenceItem,
  Passage,
  ReviewParagraph,
  Source,
} from "../types";

export const MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0";
export const MOCK_SUB = "sub_mock_juiz";
export const MOCK_EMAIL = "juiz.ficticio@exemplo.pt";

export const PUBLIC_ORIGIN = "https://dong-xuyong.github.io/law-wiki/documents";

type Seed = {
  section: string;
  text: string;
  confidence: ReviewParagraph["confidence"];
  note: string;
  sourceIds?: string[];
  evidenceIds?: string[];
};

const SOURCES: Source[] = [
  {
    id: "triave-1675",
    title: "Triave, processo 1675/2022",
    path: "raw/documents/triave/2022/law_0287fd0c2d1c09b7.md",
    document_id: "law_0287fd0c2d1c09b7",
    pinpoints: ["linhas 145–164"],
  },
  {
    id: "cicap-748",
    title: "CICAP, processo 748/2023",
    path: "raw/documents/cicap/2023/law_e2823c61be458951.md",
    document_id: "law_e2823c61be458951",
    pinpoints: ["linhas 228–245"],
  },
  {
    id: "caccl-351",
    title: "CACCL, Sentença 351.TA",
    path: "raw/documents/caccl/2022/law_bd2fc6a7737f1749.md",
    document_id: "law_bd2fc6a7737f1749",
    pinpoints: ["linhas 95–110"],
  },
  {
    id: "triave-613",
    title: "Triave, processo 613/2023",
    path: "raw/documents/triave/2023/law_21281b8b60c371e8.md",
    document_id: "law_21281b8b60c371e8",
    pinpoints: ["linhas 271–281"],
  },
];

const EVIDENCE: EvidenceItem[] = [
  {
    id: "p01",
    proposition:
      "O litígio reporta-se ao contrato de transporte do voo fictício AN 5520, Porto–Milão Malpensa, programado para 10 de janeiro de 2024, 09:30–12:55.",
    status: "proved",
    basis: "common",
  },
  {
    id: "p02",
    proposition:
      "A Reclamante pediu inicialmente €600 ao abrigo do Regulamento n.º 261/2004 e depois aditou hotel, lounge, perda laboral e o bilhete substituto.",
    status: "procedural",
    basis: "procedural_record",
  },
  {
    id: "p03",
    proposition:
      "A Reclamante compareceu; a AeroNimbo faltou à audiência e só respondeu depois de notificada por dez dias.",
    status: "procedural",
    basis: "procedural_record",
  },
  {
    id: "p05",
    proposition:
      "A AeroNimbo admitiu, para o seu cálculo, tarifa original de €134,48, tarifa substituta de €449,82 e diferencial de €315,34.",
    status: "proved",
    basis: "admission",
  },
  {
    id: "p08",
    proposition: "A resposta não invoca circunstâncias extraordinárias.",
    status: "procedural",
    basis: "procedural_record",
  },
  {
    id: "np01",
    proposition: "A distância ortodrómica Porto–Milão Malpensa é 1 488 km.",
    status: "not_proved",
    basis: "unilateral_assertion",
  },
  {
    id: "np04",
    proposition: "A Reclamante pagou €50 de hotel em Milão e perdeu a reserva.",
    status: "not_proved",
    basis: "unseen_attachment",
  },
  {
    id: "np07",
    proposition: "A indemnização de €250 foi paga através da empresa Help.",
    status: "not_proved",
    basis: "unseen_attachment",
  },
  {
    id: "np09",
    proposition: "A transportadora ofereceu reencaminhamento em condições equivalentes.",
    status: "not_proved",
    basis: "unilateral_assertion",
  },
];

const AMOUNTS: Amount[] = [
  {
    item: "Indemnização do artigo 7.º",
    claimed: "600.00",
    awarded: "250.00",
    reason: "A banda de €600 não se aplica; €250 foi reconhecido e o pagamento alegado não está provado.",
  },
  {
    item: "Bilhete de substituição",
    claimed: "449.00",
    awarded: "315.34",
    reason: "Concede-se o diferencial admitido, depois do reembolso da tarifa original.",
  },
  {
    item: "Hotel",
    claimed: "50.00",
    awarded: "0.00",
    reason: "Pagamento, não fruição e nexo causal não provados.",
  },
  {
    item: "Lounge",
    claimed: "50.00",
    awarded: "50.00",
    reason: "Parcela incluída na proposta concreta constante da resposta.",
  },
  {
    item: "Perda de trabalho",
    claimed: "37.52",
    awarded: "0.00",
    reason: "Horas e perda remuneratória não provadas.",
  },
];

type LineRecord = { title: string; path: string; text: string };

const LINES: Record<string, LineRecord> = {
  "law_0287fd0c2d1c09b7:145:164": {
    title: "Triave, processo 1675/2022",
    path: "raw/documents/triave/2022/law_0287fd0c2d1c09b7.md",
    text: [
      "1, A reclamante comprou através do site da reclamada um bilhete para o voo",
      "com partida prevista para 28-05-2022 e regresso em 30-05-2022 —",
      "facto que se julga provado com base no doc. n.º 1 e 2 junto com a reclamação;",
      "2, O voo foi cancelado pela reclamada por motivos não",
      "concretamente apurados mas não imputáveis à reclamante — facto que se julga provado",
      "com base no depoimento do reclamante e com base no doc. n.º 7 junto com a",
      "reclamação;",
      "3. A reclamada reembolsou a reclamante no valor de €56,47 (cinquenta e seis",
      "euros e quarenta e sete cêntimos) pago pelos bilhetes para o voo",
      "facto que se julga provado com base no depoimento da reclamante;",
    ].join("\n"),
  },
  "law_e2823c61be458951:228:245": {
    title: "CICAP, processo 748/2023",
    path: "raw/documents/cicap/2023/law_e2823c61be458951.md",
    text: [
      "1. O demandante adquiriu uma passagem área para o voo Porto-Genebra “EZS1458”",
      "que estava agendado para o dia 11-03-2023, com partida prevista para as 14:50 e",
      "chegada às 18:05 locais;",
      "2. O voo atrasou-se e só partiu às 18:04 portuguesas;",
      "3. O voo chegou a Genebra às 21:09 suíças;",
      "4, O reclamante aguardou mais de três horas pelo voo;",
      "5. À reclamada não informou o reclamante antes, durante ou depois, as razões do atraso",
      "do voo;",
      "6. Durante esse período o reclamante alimentou-se e realizou uma despesa no valor de",
      "€25,45;",
    ].join("\n"),
  },
  "law_bd2fc6a7737f1749:95:110": {
    title: "CACCL, Sentença 351.TA",
    path: "raw/documents/caccl/2022/law_bd2fc6a7737f1749.md",
    text: [
      "1. A requerida tem por objeto social a exploração de serviços de transporte aéreo de passageiros.",
      "2. O voo de 14 de setembro de 2022 foi cancelado.",
      "3. O Requerente recusou o reencaminhamento para novo voo pela Requerida a 17 de setembro de 2022.",
      "4. O Requerente adquiriu e usou novo voo adquirido à companhia aérea Transavia em 17 de setembro de 2022.",
      "Dos factos não provados: o voo foi cancelado por circunstância extraordinária.",
    ].join("\n"),
  },
  "law_21281b8b60c371e8:271:281": {
    title: "Triave, processo 613/2023",
    path: "raw/documents/triave/2023/law_21281b8b60c371e8.md",
    text: [
      "Resulta do ponto 4.2. das Orientações para a Interpretação do Regulamento (CE) n.º 261/2004",
      "que sendo oferecida aos passageiros a possibilidade de continuar uma viagem ou o seu",
      "reencaminhamento, tal deve ser proposto «em condições de transporte equivalentes», devendo",
      "ser tidos em consideração diversos aspetos e analisando-se casuisticamente.",
      "O reencaminhamento deve ser oferecido sem qualquer custo adicional para o passageiro,",
      "mesmo que os passageiros sejam reencaminhados com outra transportadora aérea, noutro modo",
      "de transporte ou numa classe superior, ou a uma tarifa mais elevada do que a paga originalmente.",
    ].join("\n"),
  },
};

function seeds(title: string): Seed[] {
  return [
    {
      section: "sumario",
      confidence: "high",
      note: "O corpus local trata a indemnização do artigo 7.º como reparação forfetária da perda de tempo.",
      sourceIds: ["triave-1675"],
      text: "1. O contrato de transporte aéreo rege-se, no que ao caso importa, pelo Regulamento (CE) n.º 261/2004. A indemnização do artigo 7.º compensa a perda de tempo e não exige prova de um dano individualizado.",
    },
    {
      section: "sumario",
      confidence: "medium",
      note: "A distância exata não está provada. O montante de €250 assenta na admissão da transportadora.",
      sourceIds: ["cicap-748"],
      text: "2. Para voos intracomunitários, o artigo 7.º fixa €250 até 1 500 km e €400 acima desse limiar. A banda de €600 não é aplicável. Não tendo sido provado o pagamento alegado, subsiste a obrigação de €250 reconhecida na resposta.",
    },
    {
      section: "sumario",
      confidence: "low",
      note: "A cumulação com hotel e salário depende de prova que não consta do registo. Confirme antes de aceitar.",
      sourceIds: ["triave-613", "caccl-351"],
      text: "3. O artigo 12.º permite indemnização suplementar, mas não o duplo ressarcimento do mesmo dano. Reembolsada a tarifa original, o prejuízo do transporte substituto corresponde ao diferencial admitido e não ao preço integral do novo bilhete.",
    },
    {
      section: "relatorio",
      confidence: "high",
      note: "Relato limitado ao texto fictício fornecido. Não há número de processo.",
      text: `No caso «${title}», a Reclamante fictícia pede a condenação da AeroNimbo pelo voo AN 5520, Porto–Milão Malpensa, programado para 10 de janeiro de 2024, das 09:30 às 12:55. O pedido inicial foi de €600 ao abrigo do Regulamento n.º 261/2004.`,
    },
    {
      section: "relatorio",
      confidence: "medium",
      note: "A sequência resulta do registo processual colado, sem ata integral.",
      evidenceIds: ["p03"],
      text: "A Reclamante compareceu. A transportadora, embora notificada, faltou à audiência e não apresentara contestação. Frustrada a conciliação, a Reclamante alterou o pedido, aditando €449 pelo bilhete substituto, €50 de hotel, €50 de lounge e €37,52 por quatro horas de trabalho. A AeroNimbo respondeu depois, qualificou o voo como cancelado e propôs €365,34.",
    },
    {
      section: "objeto_litigio",
      confidence: "high",
      note: "Os quatro núcleos do pedido estão delimitados.",
      sourceIds: ["cicap-748"],
      text: "Cumpre decidir se a AeroNimbo deve pagar a indemnização do artigo 7.º, o diferencial ou o preço integral do bilhete substituto, as despesas de hotel e lounge, a perda laboral, e se o alegado pagamento através da Help extinguiu a obrigação.",
    },
    {
      section: "saneador",
      confidence: "medium",
      note: "Não se declara um tribunal arbitral constituído. Faltam competência, data e identificação completa.",
      text: "O registo não estabelece o número do processo, a identificação completa da Reclamante, a data da audiência nem o centro de arbitragem competente. Esses elementos não ficam dados como estabelecidos.",
    },
    {
      section: "saneador",
      confidence: "low",
      note: "A falta de inventário documental limita toda a prova que dependa de anexos.",
      text: "Nenhuma testemunha foi indicada e o número de documentos não é determinável. A apreciação fica limitada ao que o texto fornecido realmente contém.",
    },
    {
      section: "factos_provados",
      confidence: "high",
      note: "Matéria comum às partes.",
      evidenceIds: ["p01"],
      text: "a) O litígio reporta-se ao contrato de transporte do voo AN 5520, Porto–Milão Malpensa, programado para 10 de janeiro de 2024, 09:30–12:55.",
    },
    {
      section: "factos_provados",
      confidence: "high",
      note: "Facto processual: o que foi pedido, não o que aconteceu no aeroporto.",
      evidenceIds: ["p02"],
      text: "b) A Reclamante pediu €600 ao abrigo do Regulamento n.º 261/2004 e alterou o pedido para aditar €449, €50 de hotel, €50 de lounge e €37,52 de perda laboral.",
    },
    {
      section: "factos_provados",
      confidence: "medium",
      note: "Admissão da Reclamada para o seu cálculo. Não há fatura no registo.",
      evidenceIds: ["p05"],
      text: "c) A AeroNimbo admitiu tarifa original de €134,48, tarifa substituta de €449,82 e diferencial de €315,34, e não invocou circunstâncias extraordinárias.",
    },
    {
      section: "factos_nao_provados",
      confidence: "medium",
      note: "Alegação unilateral da transportadora, sem medição independente.",
      evidenceIds: ["np01"],
      text: "aa) Que a distância ortodrómica Porto–Milão Malpensa seja 1 488 km.",
    },
    {
      section: "factos_nao_provados",
      confidence: "low",
      note: "Anexo não junto. Não promova este facto a provado.",
      evidenceIds: ["np04"],
      text: "bb) Que a Reclamante tenha pago €50 de hotel em Milão e perdido a reserva por impossibilidade de check-in.",
    },
    {
      section: "factos_nao_provados",
      confidence: "low",
      note: "Facto extintivo. O ónus é da transportadora e o comprovativo não foi junto.",
      evidenceIds: ["np07"],
      text: "cc) Que a indemnização de €250 tenha sido paga através da empresa Help, e que tenha sido oferecido reencaminhamento equivalente.",
    },
    {
      section: "motivacao",
      confidence: "high",
      note: "O artigo 342.º do Código Civil, como aplicado no corpus, reparte o ónus.",
      sourceIds: ["cicap-748"],
      text: "À parte que invoca o direito cabe o ónus dos factos constitutivos. À contraparte cabe o ónus dos factos impeditivos ou extintivos. A falta de documentos impede tratar hotel, trabalho e pagamento Help como factos materiais provados.",
    },
    {
      section: "motivacao",
      confidence: "medium",
      note: "No precedente Triave 1675/2022 a ausência não dispensou prova dos danos.",
      sourceIds: ["triave-1675"],
      text: "A falta da transportadora à audiência não torna o pedido procedente. Distingue-se a prova de que uma alegação foi feita da prova de que o facto alegado ocorreu.",
    },
    {
      section: "fundamentacao_direito",
      confidence: "high",
      note: "Quadro do artigo 7.º estável nos precedentes locais.",
      sourceIds: ["caccl-351", "cicap-748"],
      text: "O artigo 7.º fixa €250 até 1 500 km, €400 para os voos intracomunitários de maior distância e para os demais entre 1 500 e 3 500 km, e €600 fora dessas bandas. A Reclamada reconhece €250 e a Reclamante não provou distância superior a 1 500 km, pelo que o excesso até €600 improcede.",
    },
    {
      section: "fundamentacao_direito",
      confidence: "medium",
      note: "Há precedentes em sentido diverso sobre o bilhete comprado pelo passageiro. A solução segura é o diferencial.",
      sourceIds: ["triave-613", "triave-1675"],
      text: "Não se provou oferta de reencaminhamento equivalente. Também não pode somar-se a tarifa já reembolsada ao preço integral do substituto. Concede-se o diferencial de €315,34 admitido pela AeroNimbo (€449,82 menos €134,48).",
    },
    {
      section: "fundamentacao_direito",
      confidence: "low",
      note: "A concessão do lounge é frágil: não há autoridade local que o trate como rubrica autónoma. Confirme a proposta processual.",
      sourceIds: ["caccl-351"],
      text: "Hotel e perda laboral improcedem por falta de prova. O lounge de €50 foi incluído pela própria transportadora na proposta de €365,34, sem o condicionar à junção da fatura. Essa posição limita a controvérsia nessa parcela.",
    },
    {
      section: "decisao",
      confidence: "high",
      note: "A soma €250 + €315,34 + €50 é €615,34, igual ao total da tabela.",
      text: "Julga-se a ação parcialmente procedente e condena-se a AeroNimbo a pagar à Reclamante fictícia €615,34: €250 do artigo 7.º, €315,34 de diferencial do bilhete e €50 da parcela de lounge assumida na resposta.",
    },
    {
      section: "decisao",
      confidence: "medium",
      note: "Confirme cada absolvição. Nada se deduz a título de pagamento Help.",
      text: "Absolve-se a Reclamada do demais: do excesso entre €600 e €250, do preço integral do bilhete, do hotel e da perda de trabalho. Não se deduz qualquer quantia pelo pagamento Help, que não ficou provado. O valor da causa fictícia fixa-se em €1 186,52.",
    },
  ];
}

export type DraftBody = {
  paragraphs: ReviewParagraph[];
  evidence: EvidenceItem[];
  sources: Source[];
  amounts: Amount[];
  decisionTotal: string;
};

export function buildDraftBody(title: string): DraftBody {
  const counts = new Map<string, number>();
  const paragraphs: ReviewParagraph[] = seeds(title).map((seed) => {
    const index = counts.get(seed.section) ?? 0;
    counts.set(seed.section, index + 1);
    return {
      id: `${seed.section}-${index}`,
      section: seed.section,
      index,
      text: seed.text,
      sourceIds: seed.sourceIds ?? [],
      evidenceIds: seed.evidenceIds ?? [],
      confidence: seed.confidence,
      note: seed.note,
      originalText: seed.text,
      review: { status: "pending", by: "", at: "" },
    };
  });
  return {
    paragraphs,
    evidence: EVIDENCE.map((item) => ({ ...item })),
    sources: SOURCES.map((source) => ({ ...source, pinpoints: [...source.pinpoints] })),
    amounts: AMOUNTS.map((amount) => ({ ...amount })),
    decisionTotal: "615.34",
  };
}

export function lookupLines(
  documentId: string,
  start: number,
  end: number,
): LineRecord | null {
  return LINES[`${documentId}:${start}:${end}`] ?? null;
}

export function searchCorpus(query: string, k: number): Passage[] {
  const needle = fold(query.trim());
  if (!needle) return [];
  const hits: Passage[] = [];
  for (const source of SOURCES) {
    for (const pinpoint of source.pinpoints) {
      const range = pinpoint.match(/(\d+)\D+(\d+)/);
      if (!range) continue;
      const lineStart = Number(range[1]);
      const lineEnd = Number(range[2]);
      const record = lookupLines(source.document_id, lineStart, lineEnd);
      if (!record) continue;
      const haystack = fold(`${source.title}\n${record.text}`);
      if (!haystack.includes(needle)) continue;
      hits.push({
        document_id: source.document_id,
        path: source.path,
        title: source.title,
        line_start: lineStart,
        line_end: lineEnd,
        text: record.text,
        score: 0,
      });
    }
  }
  hits.forEach((hit, index) => {
    hit.score = Number((1 - index * 0.08).toFixed(2));
  });
  return hits.slice(0, k);
}

function fold(value: string): string {
  return value
    .toLocaleLowerCase("pt-PT")
    .normalize("NFD")
    .replace(/\p{M}/gu, "");
}
