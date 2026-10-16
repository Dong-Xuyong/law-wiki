# Dossiê para o CSM, o GAIA e o IGFEJ

**ESBOÇO.** Guião do que o dossiê deve conter. Não é o dossiê enviado, não é aconselhamento jurídico e não pede, por si, autorização de uso. A numeração das recomendações segue a página do plano de 16 de outubro de 2026, que cita as recomendações do CSM aprovadas a 8 de abril de 2026. A transcrição artigo a artigo do PDF está **a confirmar** no texto que vier a ser entregue.

Destinatários previstos: Conselho Superior da Magistratura, Grupo de Acompanhamento da Inteligência Artificial (GAIA) do CSM, e Instituto de Gestão Financeira e Equipamentos da Justiça (IGFEJ), pelo Magistratus. O caminho (CSM diretamente, ou integração no Magistratus através do IGFEJ) é uma decisão em aberto no plano.

Data do esboço: 16 de outubro de 2026.

## 1. O que é

Minutas é um protótipo privado, na região AWS `eu-west-1`, que prepara uma minuta de decisão em português para uma juíza rever parágrafo a parágrafo e, só depois, exportar um DOCX.

O que faz:

- Recebe um texto de caso fictício, ou apoia-se em decisão já publicada.
- Procura legislação e jurisprudência num corpus local, com pesquisa literal (SQLite FTS5). As autoridades não saem da memória do modelo.
- Redige a minuta com o Amazon Bedrock, perfil de inferência `eu.` (Claude Sonnet 4.5, identificador `eu.anthropic.claude-sonnet-4-5-20250929-v1:0`).
- Verifica se cada citação existe no corpus e se cada facto provado tem base `common`, `admission` ou `procedural_record`.
- Obriga a aceitar, editar ou rejeitar cada parágrafo. Não há "aceitar tudo".
- Recusa a exportação enquanto a revisão não estiver completa.
- Escreve no DOCX: `Decisão produzida com o auxílio de sistema de IA, de acordo com as recomendações do CSM. Integralmente revisto pelo signatário.`
- Mantém em cada página: `MINUTA NÃO ASSINADA — AUXÍLIO À INVESTIGAÇÃO JURÍDICA`.
- Regista cada geração e cada revisão (quem, ação, modelo, impressão digital do pedido, fontes), sem guardar o texto da peça no registo.

O primeiro alvo de desenvolvimento é o Regulamento (CE) n.º 261/2004, com jurisprudência do TJUE e acórdãos publicados no dgsi. A juíza ainda não respondeu ao questionário sobre o tipo de decisão. Esse alvo pode mudar.

O enquadramento de risco, na página do plano: anexo III, ponto 8, alínea a), do Regulamento da IA. O Regulamento (UE) 2026/1744 fixa o início das obrigações de risco elevado desse anexo em 2 de dezembro de 2027. Os rascunhos de documentação técnica, de AIPD e de avaliação de impacto nos direitos fundamentais acompanham este esboço e estão por rever pela entidade pública.

## 2. O que não é

- Não é um sistema fornecido pelo sistema de tramitação processual nem pelo CSM.
- Não está validado. Não está integrado no Magistratus.
- Não é para processos reais. A API exige `fictional: true`.
- Não produz uma decisão assinada. A marca de minuta não assinada permanece.
- Não substitui a fundamentação da juíza e o resultado não é vinculativo (diretrizes CEPEJ de 2025).
- Não é o ambiente de produção. A conta AWS é de desenvolvimento, pessoal, em modo económico (sem WAF, alarme de orçamento de 10 USD por mês). A produção, se existir, fica contratada ou operada pelo IGFEJ ou pelo CSM.
- Não reutiliza peças para treinar modelos.
- Não é aconselhamento jurídico nem uma declaração UE de conformidade.

## 3. Conformidade com as recomendações do CSM, ponto por ponto

Texto de cada ponto: o que a página do plano diz que a recomendação diz. Cumprimento: o que o protótipo faz hoje.

### Recomendações 4 e 6

O que dizem, na página do plano: os juízes só devem usar sistemas de IA e minutas fornecidos pelo sistema de tramitação processual ou pelo CSM. Os sistemas disponibilizados pelo sistema de tramitação ficam sujeitos a controlo de qualidade e auditoria do CSM.

Cumprimento hoje: não cumprido como autorização de uso judicial, e não é isso que se pede. O protótipo não é oferecido à juíza para processos reais. A conta pessoal serve para desenvolvimento e para esta demonstração. O controlo de qualidade e a auditoria do CSM ainda não ocorreram. É o objeto do pedido na secção 6.

### Recomendação 8

O que diz: ferramentas não fornecidas podem ser usadas para estudo apenas com fontes abertas. Dados judiciais nunca. Elementos processuais só anonimizados.

Cumprimento hoje: as fases 1 e 2 estão desenhadas assim. Corpus aberto (legislação, jurisprudência publicada, incluindo o alvo 261/2004). Casos fictícios obrigatórios na API. Não há carregamento autorizado de dados judiciais. Se um ficheiro real entrar por engano, o procedimento é apagar os objetos e os itens e lavrar nota sem o conteúdo (`RUNBOOK.md`).

Ponto aberto: acórdãos publicados no dgsi podem conter nomes. São fonte aberta. A necessidade de anonimização suplementar desses nomes está **a confirmar**.

### Recomendação 6.5

O que diz, agrupada na página do plano com as recomendações 9.5 e 10: a minuta é gerada só por vontade do juiz e pode ser livre e integralmente modificada.

Cumprimento hoje: a geração só começa com `POST /api/cases/{caseId}/drafts`, feito pelo utilizador autenticado. Cada parágrafo pode ser aceite, editado ou rejeitado. O texto editado é o que segue para o DOCX. Não há ação de aceitar tudo. A modificação "integral" depende de a interface cobrir todos os parágrafos, o que o contrato da API prevê e a demonstração deve mostrar.

### Recomendação 9.5

O que diz, na mesma leitura da página do plano: rastreabilidade das operações e impossibilidade de reutilizar os dados para fins diferentes.

Cumprimento hoje: item de auditoria por geração, aceitação, edição, rejeição e exportação, com modelo, impressão digital do pedido e identificadores de fonte. O texto da peça não vai para o registo. Não há fluxo de treino. A garantia contratual de que o Bedrock não usa os pedidos para treinar modelos é a que a AWS publica; o contrato da entidade pública com o fornecedor, exigido pelas diretrizes CEPEJ de 2025, não existe e não pode existir enquanto a infraestrutura for uma conta pessoal. Isso fica para a produção.

Prazo de conservação dos registos: **a definir**.

### Recomendação 10

O que diz, na página do plano: declaração do uso na decisão.

Cumprimento hoje: a frase do CSM é acrescentada ao DOCX no momento da exportação, e só se a revisão estiver completa. A exportação incompleta responde 409.

### O que estas recomendações não esgotam

O plano também condiciona o projeto ao Regulamento da IA (artigos 9.º a 15.º, 26.º, 27.º e 49.º), ao Regulamento (UE) 2026/1744, às diretrizes CEPEJ de 2025 e ao RGPD com a Lei n.º 34/2009, artigos 23.º e 24.º. Os rascunhos correspondentes estão em:

- `ai-act-documentacao-tecnica.md`
- `aipd-rascunho.md`
- `avaliacao-impacto-direitos-fundamentais-rascunho.md`

Nenhum deles está aprovado. São material para o GAIA comentar, não documentos entregues como finais.

## 4. Demonstração

Demonstração proposta, com um caso fictício de 261/2004, sem nomes reais:

1. Entrar com utilizador criado pelo administrador e MFA por TOTP. Mostrar que o auto-registo está desligado.
2. Mostrar a marca de minuta não assinada.
3. Criar o caso fictício. Mostrar que a API recusa um caso sem `fictional: true`.
4. Pedir a minuta. Mostrar que nada é gerado antes desse pedido.
5. Abrir uma citação e o excerto do corpus (linhas de origem). Mostrar uma passagem que o verificador não confirma, se o ensaio a produzir.
6. Tentar exportar antes de rever: a exportação falha.
7. Aceitar, editar e rejeitar parágrafos, sem botão de aceitar tudo.
8. Exportar o DOCX e ler a declaração de uso de IA e de revisão integral.
9. Mostrar o registo de auditoria correspondente, sem o texto da peça.

A demonstração gasta cerca de 1 USD de modelo, na estimativa do plano (intervalo publicado: 1 a 1,50 USD por minuta). Não usa WAF: esse ponto diz-se de forma explícita, como risco aceite só no desenvolvimento.

## 5. Métricas

Ainda não medidas. O plano de avaliação do protótipo é: 10 casos fictícios e 10 testes retrospetivos, com `python -m app.eval run --offline` para a parte que não chama o modelo. Resultados: **a preencher**.

Critérios já escritos na página do plano, para quando houver números:

| Fase | Critério |
|---|---|
| 1 | Pelo menos 95% de precisão revista e zero citações inexistentes numa amostra auditada |
| 2 | Zero citações inventadas, factos ligados à prova, tempo de revisão inferior ao tempo de redação, medido pela juíza |
| 3 | Validação escrita do CSM ou integração aprovada no sistema de tramitação |
| 4 | Métricas estáveis durante o piloto e relatório ao CSM |

Até a fase 2 ter números revistos pela juíza, o dossiê não deve afirmar qualidade do modelo. Deve afirmar o que o verificador impede (citação ausente do corpus, exportação sem revisão) e o que ainda não foi medido.

## 6. Pedido concreto

Pede-se ao GAIA e ao CSM, com conhecimento do IGFEJ:

1. Confirmar se o uso atual (fontes abertas e casos fictícios, sem dados judiciais, numa conta de desenvolvimento) cabe na recomendação 8, e que condições adicionais o GAIA põe a essa fase.
2. Indicar o caminho de validação: apreciação direta pelo CSM, ou integração no Magistratus através do IGFEJ. O plano deixa esta escolha em aberto.
3. Dizer que peças deste esboço (documentação técnica, AIPD, avaliação de impacto nos direitos fundamentais, demonstração) o GAIA quer ver na primeira reunião, e em que formato.
4. Confirmar que nenhum piloto com processos reais começa antes de validação escrita, e quem será o responsável pelo tratamento e o implantador (leitura de trabalho do plano: CSM e juízes do processo, Lei n.º 34/2009, artigos 23.º e 24.º; infraestrutura pelo IGFEJ ou pelo CSM). **A confirmar** por essas entidades.
5. Fixar, quando for o momento, o prazo de conservação e a regra de eliminação.

Não se pede autorização para usar o protótipo em processo pendente. Não se pede que a conta AWS pessoal passe a sistema de produção.
