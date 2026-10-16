# Avaliação de impacto nos direitos fundamentais

**RASCUNHO.** Texto de apoio a uma avaliação de impacto nos direitos fundamentais nos termos do artigo 27.º do Regulamento da IA, alíneas a) a f). Quem a tem de fazer, quando o sistema for implantado, é o organismo público implantador (o tribunal), não a equipa que constrói o protótipo. Este ficheiro não é essa avaliação, não é aconselhamento jurídico e não autoriza implantação.

O Regulamento (UE) 2026/1744 adia as obrigações de risco elevado do anexo III para 2 de dezembro de 2027. O artigo 27.º insere-se nesse conjunto, na leitura de trabalho desta página: **a confirmar** no texto consolidado se alguma alteração do Regulamento (UE) 2026/1744 mudou a redação das alíneas. As alíneas usadas abaixo são as do artigo 27.º tal como em vigor no Regulamento da IA antes desse ponto de calendário: processo de utilização, período e frequência, categorias de pessoas, riscos de dano, supervisão humana, e medidas se o risco se concretizar.

Data: 16 de outubro de 2026. Sistema: Minutas. Estado: protótipo de desenvolvimento com casos fictícios e decisões publicadas. Piloto com processos reais: não iniciado.

O plano público classifica a geração de minutas para uma autoridade judiciária no anexo III, ponto 8, alínea a): sistema de risco elevado que assiste a investigar e interpretar factos e direito e a aplicá-lo a um caso concreto. Os artigos 26.º, 27.º e 49.º cabem a quem implanta: supervisão humana, monitorização, informação às pessoas abrangidas, esta avaliação, notificação da autoridade de fiscalização do mercado e registo da utilização. Nada disto foi feito, porque não há implantação.

## a) Processos do implantador em que o sistema seria usado

Processo previsto, ainda não aprovado: numa ação judicial de um único tipo, a juíza pede uma minuta a partir das peças, revê cada parágrafo, e só então pode exportar um DOCX que declara o auxílio de IA e a revisão integral pelo signatário. A decisão continua a ser da juíza. O resultado do sistema não é vinculativo (diretrizes CEPEJ de 2025 sobre IA generativa nos tribunais).

O primeiro alvo de desenvolvimento é o Regulamento (CE) n.º 261/2004. O questionário ainda não fixou o tipo de decisão. O processo judicial concreto (tribunal, espécie, fase processual) está **a confirmar**.

O que o processo de desenvolvimento faz hoje, e que não é implantação judicial: pesquisa sobre fontes abertas e geração de minutas a partir de texto fictício ou de decisão já publicada, numa conta AWS pessoal, para demonstração ao CSM e ao IGFEJ.

Processos em que o sistema não entra: prolação automática, junção ao processo eletrónico sem o magistrado, uso por quem não é o magistrado do processo, e qualquer uso antes de validação escrita do CSM ou de integração aprovada no Magistratus.

## b) Período e frequência de utilização

Utilização prevista no piloto, se a fase 3 for ultrapassada: uma juíza, um tipo de decisão, durante o período que o CSM fixar. O plano estima, como ordem de grandeza de custo, cerca de 30 minutas por mês. Esse número não é um compromisso de frequência. Frequência real: **a confirmar** com a juíza.

Cada utilização é um ato isolado: um pedido de geração, uma revisão, uma exportação eventual. Não há monitorização contínua de pessoas. Não há decisão periódica tomada pelo sistema.

Calendário institucional: a documentação começa em 2026. As obrigações do anexo III, nos termos do Regulamento (UE) 2026/1744, contam-se a partir de 2 de dezembro de 2027. Implantação em processo real antes da validação do CSM está fora deste calendário.

## c) Categorias de pessoas e grupos susceptíveis de ser afetados

No piloto real, se existir:

- Partes no processo (passageiros e transportadoras aéreas, se o tipo de decisão for o 261/2004; **a confirmar**).
- Outras pessoas nomeadas nas peças (testemunhas, representantes, menores a cargo quando o processo os mencione).
- A juíza utilizadora, quanto ao registo de que usou o sistema e quanto ao tempo de revisão.
- O público, de forma indireta, se uma minuta pouco revista degradar a qualidade das decisões nesse tipo de litígio.

Grupos que o plano já trata como expostos a viés: pessoas cujo caso se parece com jurisprudência antiga que o corpus sobre-representa. A mitigação prevista é mostrar decisões em sentido contrário e a distribuição de resultados, não uma resposta única. Se o corpus de 261/2004 tiver esse desequilíbrio: **a confirmar** quando o corpus existir.

No ambiente atual não há pessoas de processo real afetadas pelo tratamento, porque esse tratamento não ocorre. Podem existir nomes em acórdãos já publicados, que o corpus reproduz como fonte aberta.

## d) Riscos de dano para essas categorias

Informação do fornecedor ao abrigo do artigo 13.º (instruções de uso): ainda não existe um manual do fornecedor. Este rascunho e `ai-act-documentacao-tecnica.md` são o material de trabalho. Riscos específicos:

| Risco de dano | Quem | Notas |
|---|---|---|
| Minuta com citação falsa ou facto sem prova, se a revisão falhar | Partes | Direito a uma decisão fundamentada e a um processo equitativo. A Carta dos Direitos Fundamentais, artigos 47.º e, no que toca a dados, 7.º e 8.º, é a lista de trabalho; a lista fechada pelo implantador está **a confirmar** |
| Viés de automatização: o magistrado aceita texto que não leria com o mesmo cuidado | Partes | O plano trata isto como risco principal de desenho |
| Discriminação herdada da jurisprudência passada | Grupo sobre-representado ou sub-representado no corpus | Artigo 21.º da Carta, como lista de trabalho. Evidência no corpus 261/2004: **a confirmar** |
| Divulgação ou conservação excessiva de dados do processo | Pessoas identificadas nas peças | Desenvolvido na AIPD (`aipd-rascunho.md`). Lei n.º 34/2009, artigos 23.º e 24.º |
| Uso de ferramenta não validada em processo real | Partes e administração da justiça | Recomendações 4 e 6 do CSM: os juízes usam sistemas e minutas fornecidos pelo sistema de tramitação ou pelo CSM |
| Indisponibilidade do fornecedor de modelo no dia da decisão | Juíza e partes | Atraso. O sistema tem de falhar de forma visível (`status: failed`) e não apresentar uma minuta a meio |

Gravidade no estado atual: o dano às partes de um processo concreto não se pode produzir pelo canal previsto, porque o canal real está fechado. O dano residual é operacional (custo, abuso do site sem WAF) e não é um dano de direitos fundamentais das partes.

## e) Supervisão humana, segundo as instruções de uso

Instruções de uso deste protótipo, que o implantador terá de adotar ou substituir:

- A juíza pede a geração. Ninguém a dispara por rotina.
- Cada parágrafo é aceite, editado ou rejeitado. Não existe "aceitar tudo".
- As passagens de confiança baixa (`low`) são as primeiras a ler. A confiança é `high`, `medium` ou `low`.
- A exportação fica bloqueada enquanto houver parágrafo pendente ou uma secção obrigatória vazia.
- O documento declara o auxílio de IA e a revisão integral pelo signatário, com a frase fixada no contrato da aplicação.
- Cada página mantém `MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA`.
- As citações têm de existir no corpus local. O que não se confirma não vale como citação.
- Um facto só entra como provado com base `common`, `admission` ou `procedural_record`.

Estas medidas correspondem ao que a página do plano resume das recomendações 6.5, 9.5 e 10 do CSM. A redação literal dessas recomendações no PDF do CSM está **a confirmar** no dossiê formal; aqui segue-se a página do plano de 16 de outubro de 2026.

A supervisão humana não está demonstrada por métricas. O critério combinado é o tempo de revisão inferior ao tempo de redação, medido pela juíza. Valor: **a preencher**.

## f) Medidas se o risco se concretizar

Governação interna prevista, ainda sem titular institucional:

- Minuta com erro detetado antes da assinatura: rejeitar ou editar o parágrafo; não exportar. O registo de auditoria fica com a ação `reject` ou `edit` e com a impressão digital do texto, sem o texto da peça.
- Minuta com erro detetado depois de a juíza ter usado o texto: o procedimento de retificação da decisão é o do processo civil, na mão do tribunal. Este sistema não corrige uma sentença proferida. Procedimento interno de comunicação ao CSM: **a confirmar**.
- Peça real carregada no ambiente de desenvolvimento: parar, apagar os objetos S3 e os itens DynamoDB desse caso, lavrar nota de auditoria sem o conteúdo, e avisar o responsável do projeto. Passos em `RUNBOOK.md`.
- Suspeita de citação inventada que passou a verificação: bloquear novas gerações desse modelo até se perceber a falha, conservar o `draftId` e os `sourceIds`, e não repetir o caso real em tickets.
- Queixa de uma parte sobre o uso de IA: canal **a confirmar**. O artigo 27.º pede um mecanismo de queixa. O plano não o desenha. Candidatos naturais são o tribunal e o CSM; a escolha é do implantador.
- Incidente de segurança com dados pessoais: o procedimento de violação de dados do RGPD, na mão do responsável pelo tratamento. Esse responsável está **a confirmar** (leitura de trabalho: CSM e juízes do processo, Lei n.º 34/2009).
- Deriva de qualidade no piloto: o critério da fase 4 é métricas estáveis e relatório ao CSM. Limiares numéricos: **a definir**.

Notificação à autoridade de fiscalização do mercado e registo da utilização (artigos 27.º e 49.º): não aplicáveis a este protótipo, porque não há implantação de sistema de risco elevado. Ficam como passo do dossiê da fase 3, depois da validação.

## O que falta para este rascunho deixar de ser rascunho

- Implantador identificado e este texto revisto por essa entidade.
- Tipo de decisão fechado pela juíza.
- Instruções de uso do artigo 13.º estáveis.
- Métricas da avaliação (`python -m app.eval run --offline`, 10 casos fictícios e 10 testes retrospetivos) preenchidas.
- Confirmação da redação das alíneas a) a f) no texto consolidado após o Regulamento (UE) 2026/1744.
- Decisão do CSM sobre se o protótipo pode ser demonstrado e, mais tarde, implantado.
