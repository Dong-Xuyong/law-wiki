# Avaliação de impacto sobre a proteção de dados (AIPD)

**RASCUNHO.** Documento de trabalho para uma AIPD nos termos do artigo 35.º do RGPD, relativa a um piloto futuro com dados reais. Esse piloto não existe. O ambiente atual não trata peças de processos reais. Este texto não é aconselhamento jurídico, não foi submetido a um encarregado de proteção de dados e não substitui a AIPD que o responsável pelo tratamento vier a aprovar.

Data: 16 de outubro de 2026. Sistema: Minutas, ambiente de desenvolvimento em `eu-west-1`.

O artigo 35.º, n.º 7, pede uma descrição sistemática das operações e das finalidades, uma avaliação da necessidade e da proporcionalidade, uma avaliação dos riscos para os direitos e liberdades, e as medidas previstas. As secções abaixo seguem esse esquema. Onde a página do plano ou o contrato da aplicação não fixam o ponto, está escrito **a confirmar** ou **a definir**.

## Situação atual

Tratamento real de dados de processos: nenhum.

O que o ambiente de desenvolvimento pode conter:

- Legislação e jurisprudência publicadas (corpus aberto), incluindo, como alvo de desenvolvimento, o Regulamento (CE) n.º 261/2004, jurisprudência do TJUE e acórdãos do dgsi.
- Casos fictícios, com a marca `fictional: true` obrigatória na API.

Os acórdãos publicados podem incluir nomes e outros dados pessoais já tornados públicos pelo tribunal de origem. São usados como fonte de estudo, ao abrigo da recomendação 8 do CSM (8 de abril de 2026). Não se lhes acrescenta peça não publicada. A necessidade de uma máscara adicional desses nomes no índice de desenvolvimento está **a confirmar**.

A AIPD completa tem de existir antes de qualquer piloto com peças reais. As recomendações do CSM, a Lei n.º 34/2009 e as diretrizes CEPEJ de 2025 sobre IA generativa nos tribunais impedem esse piloto enquanto o CSM não valide a ferramenta e a infraestrutura não esteja sob a autoridade pública competente.

## Tratamento previsto no piloto futuro

Descrição do tratamento que esta AIPD prepara, e que hoje não ocorre:

- A juíza carrega peças de um processo (petição, contestação, documentos, atas), num único tipo de decisão, numa conta pessoal de magistrado com MFA.
- O sistema extrai pedidos, factos alegados, factos admitidos e meios de prova, com a localização no documento de origem.
- Um modelo no Amazon Bedrock, perfil de inferência `eu.`, redige uma minuta. O texto das peças e a minuta ficam em S3 cifrado com KMS. O estado da revisão fica em DynamoDB.
- A juíza revê cada parágrafo. O DOCX só é emitido depois da revisão completa e declara o uso de IA.
- Registos de auditoria guardam identificadores, ações e impressões digitais, não o texto da peça.

Dados pessoais esperados num processo de 261/2004, se o piloto vier a ser esse tipo de decisão (**a confirmar** com a juíza): identificação de passageiros, referências de reserva, dados do voo, montantes, e o que mais constar das peças. Categorias especiais (saúde, por exemplo um atestado junto ao pedido) podem aparecer mesmo num litígio de transporte. Tratar essas categorias no piloto: **a confirmar**, e em princípio a evitar por minimização.

Titular dos dados: as pessoas identificadas nas peças. Responsável pelo tratamento, nos tribunais judiciais: o plano lê a Lei n.º 34/2009, artigo 24.º, no sentido de que o CSM gere os dados, e o artigo 23.º no sentido de que a responsabilidade cabe também aos magistrados com competência sobre o processo. A qualificação exata de responsável e de subcontratante (tribunal, CSM, IGFEJ, AWS, equipa de desenvolvimento) está **a confirmar**. Nesta fase a conta AWS pessoal não é responsável por dados judiciais, porque esses dados não podem lá entrar.

Destinatários previstos: a juíza utilizadora; a AWS como operadora de infraestrutura, ao abrigo de contrato da autoridade pública com o fornecedor (CEPEJ 2025). Esse contrato não existe. Transferências para fora da UE: o desenho usa apenas perfis `eu.`. Os destinos concretos leem-se com `GetInferenceProfile` e estão **a confirmar** em cada conta. Não está previsto envio para uma região fora da União Europeia.

Conservação: **a definir** com o CSM. O plano pede prazos definidos e eliminação automática no fim do prazo. O ambiente de desenvolvimento não tem esse prazo configurado.

## Finalidades

Finalidade do piloto futuro: preparar uma minuta para o magistrado rever, num único tipo de decisão, com citação verificável e registo do uso de IA.

Finalidades que não são admitidas:

- Decidir no lugar do magistrado.
- Reutilizar as peças para treinar modelos, para estatística de outro processo, ou para fim diferente do pedido de minuta (recomendações 6.5, 9.5 e 10 do CSM, na leitura da página do plano: geração só por vontade do juiz, modificação livre, rastreabilidade, impossibilidade de reutilizar os dados para fins diferentes, declaração do uso na decisão).
- Estudo com dados judiciais não anonimizados em ferramentas não validadas pelo CSM (recomendação 8).

Base de licitude do piloto real: **a confirmar**. O plano não a escolhe. O tratamento de dados nos tribunais judiciais segue a Lei n.º 34/2009 e o RGPD. Não se inventa aqui um interesse legítimo.

## Necessidade e proporcionalidade

O plano justifica a ferramenta pela preparação da minuta com prova ligada ao facto e com citação exata, mantendo a decisão na mão da juíza. A necessidade face a alternativas (pesquisa manual, minuta sem modelo de linguagem) não está medida. Fica **a confirmar** quando a juíza comparar o tempo de revisão com o tempo de redação (critério da fase 2).

Proporcionalidade pretendida, se o piloto for autorizado:

- Um tipo de decisão, uma juíza, um universo pequeno (o plano estima cerca de 30 minutas por mês como ordem de grandeza de uso, não como autorização).
- Geração só a pedido.
- Dados limitados às peças desse processo, apagados no prazo que o CSM definir.
- Pseudonimização quando a CEPEJ de 2025 a exige para o uso de IA generativa. O momento e a técnica dessa pseudonimização estão **a confirmar**. O ambiente atual evita o problema ao não receber o processo real.
- Sem partilha com o portal público.
- Sem "aceitar tudo" e sem exportação antes da revisão, para reduzir o risco de uma minuta não lida se tornar decisão.

Enquanto o CSM não validar, a medida proporcional é não tratar dados reais. É o que o ambiente faz hoje.

## Riscos

Riscos para os direitos e liberdades se o piloto avançar sem as medidas, ou se alguém carregar um processo real no ambiente de desenvolvimento:

| Risco | Efeito |
|---|---|
| Carregamento de um processo real antes da validação | Tratamento ilícito de dados judiciais; quebra das recomendações 4, 6 e 8 do CSM |
| Texto da peça em registos, bilhetes ou histórico do Step Functions | Acesso por quem opera a conta, para além da juíza do processo |
| Acesso entre utilizadores | Um magistrado lê o processo de outro |
| Balde público ou ligação partilhável longa | Divulgação das peças |
| Pedido ao Bedrock fora de um perfil `eu.` | Possível saída da UE. O desenho proíbe esse perfil; a confirmação é operacional |
| Conservação indefinida | Incumprimento da limitação de conservação. O prazo ainda não existe |
| Erro da minuta que entra na decisão | Efeito sobre as partes. É sobretudo um risco para o direito a uma decisão fundamentada; a medida de mitigação é a revisão humana, descrita no outro rascunho |
| Categorias especiais escondidas nas peças | Tratamento excessivo se o sistema não as separar. Procedimento: **a confirmar** |
| Pedido de acesso, retificação ou apagamento por um titular | Não há procedimento. **A confirmar** com o CSM, que o plano indica como gestor dos dados nos tribunais judiciais |

Probabilidade no ambiente atual: baixa para o tratamento de processos reais, porque a API recusa casos sem `fictional: true` e a regra de operação proíbe o carregamento. A probabilidade não é zero: alguém pode colar um processo real no campo de texto e marcar o caso como fictício. Esse desvio é um incidente (ver `RUNBOOK.md`), não um tratamento autorizado.

A consulta prévia à autoridade de controlo, se a AIPD final mostrar risco residual elevado (artigo 36.º do RGPD), está **a confirmar**. O mesmo vale para o parecer do encarregado de proteção de dados (artigo 35.º, n.º 2).

## Medidas

Medidas já desenhadas para o ambiente de desenvolvimento, e que um piloto teria de herdar ou reforçar:

- Separação entre o portal público e a conta privada.
- Casos só com `fictional: true` até validação do CSM.
- Cognito sem auto-registo e com MFA por TOTP.
- JWT em todas as rotas e verificação de que o titular do item é o `sub` do token.
- S3 de peças com cifra KMS; baldes privados; CloudFront com OAC para a interface.
- Bedrock apenas com perfil `eu.`; destinos confirmados com `get-inference-profile`.
- Auditoria por hashes e identificadores de fonte, sem texto da peça nos registos.
- IAM de privilégio mínimo (**políticas concretas a confirmar** no CDK).
- CloudTrail.
- Exportação bloqueada até à revisão completa de cada parágrafo.
- Procedimento de incidente: apagar os objetos S3 e os itens DynamoDB do caso e lavrar nota de auditoria sem copiar o conteúdo.
- Alarme de orçamento de 10 USD por mês, como travão de uso anómalo no modo económico.

Medidas ainda em aberto, obrigatórias antes de dados reais:

- Responsável pelo tratamento, subcontratantes e contrato com a AWS, definidos pela entidade pública. **A confirmar.**
- Prazo de conservação e eliminação automática. **A definir.**
- Pseudonimização das peças, se o piloto a exigir. **A confirmar.**
- Procedimento para os direitos dos titulares e para a violação de dados. **A confirmar.**
- AIPD aprovada e, se necessário, consulta prévia. **A confirmar.**
- Decisão sobre WAF e sobre a região soberana. O modo económico sem WAF é um risco aceite só em desenvolvimento, com dados fictícios e publicados. Não é medida suficiente para um piloto real.

## Ligação a outros rascunhos

- Direitos fundamentais: `avaliacao-impacto-direitos-fundamentais-rascunho.md`
- Documentação técnica: `ai-act-documentacao-tecnica.md`
- Dossiê para o CSM e o IGFEJ: `dossie-csm-esboco.md`
