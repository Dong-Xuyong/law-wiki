# Documentação técnica do sistema de IA

**RASCUNHO.** Este texto não é aconselhamento jurídico, não é uma avaliação de conformidade concluída e não autoriza o uso em processos reais. Não substitui a documentação do fornecedor nem a decisão do Conselho Superior da Magistratura (CSM). A validação cabe ao CSM.

Estrutura de trabalho alinhada com o anexo IV do Regulamento da IA (documentação técnica dos sistemas de risco elevado). Os pontos 7, 8 e 9 do anexo IV (normas harmonizadas, declaração UE de conformidade e plano de monitorização pós-comercialização) não estão preenchidos: não há norma escolhida, não há declaração e o sistema não está no mercado. O Regulamento (UE) 2026/1744 adia as obrigações de risco elevado do anexo III para 2 de dezembro de 2027. Este rascunho existe para esse prazo poder ser cumprido; o plano público estima 12 a 18 meses de preparação.

Versão de trabalho: 16 de outubro de 2026. Nome de trabalho: Minutas. Ambiente: desenvolvimento privado, AWS, região `eu-west-1`.

## 1. Descrição geral

Minutas prepara uma minuta de decisão em português para revisão humana, parágrafo a parágrafo, e exporta um DOCX só depois dessa revisão. O primeiro alvo de desenvolvimento é a compensação por cancelamento, atraso ou recusa de embarque ao abrigo do Regulamento (CE) n.º 261/2004, com casos fictícios ou decisões já publicadas. A escolha do primeiro tipo de decisão pela juíza, no questionário, continua em aberto (**a confirmar**).

O sistema está desenhado como componente de software, sem aparelho dedicado. A interface é uma aplicação web (português europeu) atrás de CloudFront. A geração corre em AWS Lambda e Step Functions. O modelo é chamado através do Amazon Bedrock, apenas com um perfil de inferência `eu.`. O identificador por omissão é `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`. Os destinos desse perfil confirmam-se com `aws bedrock get-inference-profile` antes de cada ambiente novo.

Formas de disponibilização previstas:

- Portal público da Legal Research Wiki (GitHub Pages): pesquisa sobre o corpus já publicado. Não recebe peças processuais.
- Ambiente de desenvolvimento na conta AWS do projeto: fontes abertas e casos fictícios.
- Produção: só depois de validação escrita do CSM ou de integração aprovada no sistema de tramitação (Magistratus, através do IGFEJ). A infraestrutura de produção é contratada ou operada pelo IGFEJ ou pelo CSM, não por um particular (diretrizes CEPEJ de 2025 sobre IA generativa nos tribunais).

Fornecedor em produção: **a confirmar** (IGFEJ ou CSM). Nesta fase o responsável pela construção é o projeto de desenvolvimento, numa conta pessoal, o que a página do plano trata como ambiente de desenvolvimento e não como sistema fornecido ao abrigo das recomendações 4 e 6 do CSM.

Cada página gerada mantém a marca `MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA`. O DOCX acrescenta: `Decisão produzida com o auxílio de sistema de IA, de acordo com as recomendações do CSM. Integralmente revisto pelo signatário.`

## 2. Finalidade prevista

Finalidade: auxiliar uma autoridade judiciária a organizar factos, a localizar legislação e jurisprudência no corpus local e a redigir uma minuta que o magistrado revê, altera e, se quiser, assina. O plano público enquadra esta finalidade no anexo III, ponto 8, alínea a), do Regulamento da IA: IA que assiste uma autoridade judiciária a investigar e interpretar factos e direito e a aplicá-lo a um caso concreto. A Comissão indica a geração de minutas de decisões como exemplo.

A minuta não é uma decisão. O resultado não é vinculativo (diretrizes CEPEJ de 2025). A geração só ocorre quando a pessoa utilizadora a pede.

Fora da finalidade: decidir o caso, substituir a fundamentação do magistrado, pesquisar direito a partir da memória do modelo, tratar processos reais antes da validação do CSM, reutilizar peças para treinar modelos ou para outro fim.

## 3. Utilizadores

Utilizador previsto da minuta: um magistrado judicial, nesta fase uma juíza, que aceita, edita ou rejeita cada parágrafo. No ambiente de desenvolvimento os utilizadores são as pessoas criadas pelo administrador no Cognito (sem auto-registo, com MFA por TOTP).

Pessoas afetadas, quando o sistema for usado num processo real: as partes e outras pessoas identificadas nas peças. Esse uso não existe hoje. A descrição dessas categorias está no rascunho da avaliação de impacto nos direitos fundamentais.

O implantador, nos termos dos artigos 26.º, 27.º e 49.º, será o tribunal (organismo público): supervisão humana, monitorização, informação às pessoas abrangidas, avaliação de impacto nos direitos fundamentais, notificação da autoridade de fiscalização do mercado e registo da utilização. Quem desempenha esse papel em concreto está **a confirmar** (CSM, tribunal, IGFEJ).

## 4. Conceção e arquitetura

Três níveis, como no plano de 16 de outubro de 2026:

1. Pesquisa sobre fontes abertas (uso de estudo, recomendação 8 do CSM).
2. Motor de minutas com casos fictícios e decisões públicas.
3. Uso em processos reais só após validação do CSM.

Fluxo da minuta: receber as peças (só a pedido); organizar pedidos, factos e prova; pesquisar legislação e jurisprudência no corpus local, incluindo decisões em sentido contrário; redigir relatório, factos provados e não provados, motivação, fundamentação de direito e dispositivo; verificar citações e montantes; rever parágrafo a parágrafo; exportar DOCX.

Peças de software, segundo `app/CONTRACTS.md`:

- Pesquisa literal: SQLite FTS5 (`python -m app.ingest.index_fts`). No modo económico da versão 1 não há S3 Vectors nem Knowledge Bases. A pesquisa semântica do plano público fica para uma fase posterior (**a confirmar** quando o volume a justificar).
- Redação: `app.engine.draft`, com o modelo atrás de uma interface própria (`LLM`), para ser possível trocar de modelo sem reescrever a ferramenta.
- Verificação: `validate_packet` e confirmação da citação contra o texto do corpus. Uma citação que não se confirma não entra como citação válida.
- API e trabalhador: Lambda Python 3.12 e Step Functions. A API só arranca uma geração quando recebe `POST /api/cases/{caseId}/drafts`.
- Dados de trabalho: DynamoDB (minuta, parágrafos, auditoria) e S3 cifrado com KMS para as peças e para o DOCX.
- Identidade: Cognito, auto-registo desligado, MFA obrigatório.

As autoridades jurídicas saem apenas de `raw/documents/**`, catalogados em `data/catalog.jsonl` e `data/open-sources-catalog.jsonl`. Um facto só conta como provado com base `common`, `admission` ou `procedural_record`.

Recursos: Lambda `api` com 1024 MB, 30 s e 3072 MB efémeros; `draft_worker` com 1024 MB, 900 s e 3072 MB efémeros. Região `eu-west-1`. O modo económico não inclui AWS WAF; o risco aceite está descrito em `SECURITY.md`.

O modelo de documento atual é `app/engine/templates/decisao-arbitral-wiki.docx`, herdado do corpus de arbitragem de consumo. A adequação desse modelo a uma decisão de 261/2004 está **a confirmar** com a juíza (critério da fase 0: estrutura da minuta aprovada).

## 5. Dados e governação dos dados

Corpus de desenvolvimento: fontes abertas. O corpus já construído é de decisões de arbitragem de consumo (CACCL, CICAP, Triave, CNIACC e CIAB). O alvo 261/2004 acrescenta o regulamento, jurisprudência do TJUE e acórdãos publicados no dgsi, com recolha lenta e identificada. Não há, nesta fase, dados de processos reais.

Regras:

- Criar um caso exige `fictional: true`. Caso contrário a API responde 400 `fictional_required`.
- Dados judiciais não entram. Elementos processuais, se algum teste futuro os usar, só anonimizados (recomendação 8 e leitura do plano sobre a Lei n.º 34/2009).
- Os acórdãos publicados podem conter nomes de pessoas. São fonte aberta de estudo. Não se lhes junta peça não publicada. Se a máscara adicional desses nomes é exigida no ambiente de desenvolvimento: **a confirmar**.
- As peças de um futuro piloto real ficam sob controlo da autoridade pública (CEPEJ 2025). A Lei n.º 34/2009, artigo 23.º, atribui a responsabilidade a quem gere os dados e aos magistrados com competência sobre o processo; nos tribunais judiciais, o CSM gere esses dados (artigo 24.º). O plano lê isto como responsabilidade do CSM e dos juízes do processo.
- Minimização: o trabalhador recebe `caseId` e `draftId`. O texto segue em S3, não no histórico do Step Functions.
- Proibição de reutilização para fim diferente, incluindo treino de modelos de base. A AWS indica que os pedidos ao Bedrock não são usados para treinar modelos; a confirmação contratual em produção cabe à entidade pública (**a confirmar**).
- Conservação: prazo por definir com o CSM. Ver `aipd-rascunho.md`.

Conjuntos de treino do modelo de base: não são deste projeto. O projeto não treina nem ajusta o modelo. Governação de dados do artigo 10.º, na parte do modelo de base, é documentação do fornecedor do modelo (**a confirmar** no dossiê que a AWS e a Anthropic disponibilizam). A governação que este projeto controla é a do corpus jurídico e a das peças carregadas pelo utilizador.

## 6. Supervisão humana

Medidas implementadas no desenho, em linha com o artigo 14.º e com as recomendações 6.5, 9.5 e 10 do CSM, tal como a página do plano as resume:

- A minuta só é gerada por ação expressa do utilizador.
- Revisão parágrafo a parágrafo: aceitar, editar ou rejeitar. Não há ação de "aceitar tudo".
- As passagens com confiança baixa devem ser mostradas primeiro (mitigação do viés de automatização descrita no plano). A ordem exata no ecrã está **a confirmar** na aplicação web.
- A exportação responde 409 enquanto houver parágrafos por rever (`unreviewed`) ou uma secção obrigatória fique vazia (`section_empty`).
- O texto editado substitui o texto gerado. O parágrafo rejeitado sai da minuta. Cada secção obrigatória tem de permanecer com conteúdo.
- A decisão exportada declara o uso do sistema de IA e que o signatário a reviu por inteiro.
- A marca de minuta não assinada permanece em cada página.

A supervisão humana efetiva depende do tempo e da atenção do magistrado. O critério da fase 2 é que o tempo de revisão seja inferior ao tempo de redação, medido pela juíza. Esse número ainda não existe.

## 7. Exatidão, robustez e cibersegurança

Métricas da avaliação em `app/eval`. Comando offline, sem chamada ao modelo: `python -m app.eval run --offline`. A avaliação prevista no plano de trabalho é de 10 casos fictícios e 10 testes retrospetivos. Resultados: **a preencher**.

Limiares já escritos no plano, ainda por medir:

- Fase 1: pelo menos 95% de precisão revista e zero citações inexistentes numa amostra auditada.
- Fase 2: zero citações inventadas, factos corretamente ligados à prova, tempo de revisão inferior ao tempo de redação.

Robustez prevista no desenho: no máximo duas reparações automáticas (`max_repairs = 2`); se `validate_packet` falhar, o estado do rascunho é `failed` e não há exportação. Citações confirmadas contra o corpus, com correspondência exata depois de normalizar espaços. A correspondência que ignora diacríticos não é aceite para citações.

Cibersegurança: ver `SECURITY.md`. Resumo: MFA obrigatório, sem auto-registo, balde de peças com KMS, baldes privados e OAC, JWT em todas as rotas, verificação do titular, sem texto do caso nos registos, IAM de privilégio mínimo, Bedrock só com perfil `eu.`, CloudTrail, sem WAF no modo económico (risco aceite, só em desenvolvimento).

Ensaios de intrusão, de carga e de extração de dados: **a confirmar**, ainda não realizados sobre este ambiente.

## 8. Registos

Cada geração e cada revisão deixam um item de auditoria no DynamoDB (`AUDIT#{draftId}`): quem (`actor`), a ação (`generate`, `accept`, `edit`, `reject`, `export`), o parágrafo quando aplicável, o identificador do modelo, a impressão digital do pedido (`promptSha256`), as fontes (`sourceIds`) e a impressão digital do texto (`textSha256`). O registo não guarda o texto da peça.

CloudWatch recebe os registos técnicos das funções. CloudTrail recebe a atividade de gestão da conta. O plano público exige saber quem pediu a minuta, quando, que fontes usou, que versão do modelo correu e que alterações a juíza fez. Os campos acima cobrem esse pedido, desde que a aplicação web grave aceitar, editar e rejeitar. Confirmação no código: **a confirmar**.

Prazo de conservação destes registos: **a definir**.

## 9. Gestão de riscos

Sistema de gestão de riscos do artigo 9.º, em rascunho. Riscos já nomeados na página do plano e resposta prevista:

| Risco | Resposta prevista |
|---|---|
| Citações inventadas | Confirmação contra o corpus; o que não se confirma não é apresentado como citação válida |
| Revisão superficial | Revisão parágrafo a parágrafo, sem "aceitar tudo", passagens incertas primeiro |
| Lei desatualizada | Legislação com data de vigência, aplicada à data dos factos. O campo de vigência no corpus 261/2004 está **a confirmar** |
| Uso fora das recomendações do CSM | Sem dado processual antes da validação; fases 1 e 2 só com fontes abertas e casos fictícios |
| Viés das decisões passadas | Mostrar jurisprudência em sentido contrário e a distribuição de resultados |
| Dependência de um fornecedor | Chamadas ao modelo atrás de uma camada própria |
| Custo e abuso do endpoint público sem WAF | Alarme de 10 USD por mês; ver `SECURITY.md` |
| Fuga de peças reais carregadas por engano | Procedimento em `RUNBOOK.md`: apagar objetos S3 e itens DynamoDB e lavrar nota de auditoria sem copiar o conteúdo |

Riscos residuais para o piloto real (ainda sem dados): erro que a revisão humana não apanhe; identificação de pessoas em acórdãos publicados; transferência dentro da UE entre regiões do perfil `eu.` (destinos a ler em cada conta). A avaliação formal antes do piloto está nos rascunhos da AIPD e dos direitos fundamentais.

## 10. Limitações conhecidas

- Não é um sistema fornecido pelo Magistratus nem validado pelo CSM. Não pode ser usado em processo real.
- A escolha da juíza sobre o primeiro tipo de decisão ainda não chegou. O alvo 261/2004 é decisão de desenvolvimento.
- O corpus histórico é de arbitragem de consumo. Legislação 261/2004, TJUE e dgsi estão a ser acrescentados; a cobertura está **a confirmar**.
- Não há pesquisa semântica na versão 1 (sem S3 Vectors).
- Não há WAF. Risco aceite só neste ambiente.
- O reconhecimento ótico (Textract) não faz parte da versão 1. Só entra se o questionário disser que há peças em papel digitalizado.
- As métricas de exatidão estão por medir. `app/eval` estava, nesta data, por preencher.
- O modelo pode propor texto incorreto. A verificação automática não substitui a leitura do magistrado.
- O prazo de conservação não está definido.
- As obrigações de risco elevado do anexo III, nos termos do Regulamento (UE) 2026/1744, aplicam-se a partir de 2 de dezembro de 2027. Este rascunho não antecipa essa conformidade como se já estivesse certificada.

## 11. Alterações

| Data | Alteração |
|---|---|
| 2026-10-16 | Primeira versão deste rascunho, para o protótipo de desenvolvimento (modo económico, 10 agentes, sem WAF, alarme de 10 USD). |

As alterações seguintes ao sistema (modelo, corpus, regras de exportação, controlos de acesso) acrescentam-se a esta tabela e, quando o sistema for de risco elevado em utilização real, ao processo do artigo 11.º e do anexo IV. Forma desse processo em produção: **a confirmar** com a entidade pública que vier a ser fornecedor ou implantador.
