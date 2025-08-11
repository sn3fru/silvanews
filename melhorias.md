Proposta de melhorias de prompts e lógica (alinhar o backend atual ao comportamento pragmático do poc_silva)
Objetivo: tornar o filtro/classificação mais assertivos e previsíveis (no espírito do poc_silva.py), sem quebrar a taxonomia com 8 tags do backend/prompts.py.
Diagnóstico executivo
O backend atual usa 8 tags especializadas e múltiplos prompts modulares. É flexível e robusto, mas tende a “incluir demais” na etapa de extração (permissivo) e só filtrar mais tarde (sanitização), o que dá sensação de “ruído”.
O poc_silva.py opera com prompts e faixas de score simples, claras e focadas, com regras de rejeição e bandas (P1, P2, P3) intuitivas. Isso reduz ruído cedo.
Proposta: manter as 8 tags e a estrutura do backend, porém incorporar o “estilo de filtro” do poc_silva.py: permitir menos na extração; explicitar allow list/reject list; e usar bandas de score e decisões determinísticas mais duras.
Diferenças principais (lado a lado)
Tags/taxonomia
Atual (backend/prompts.py): 8 tags especializadas em TAGS_SPECIAL_SITUATIONS + mapeamento determinístico assunto ➜ (tag, prioridade).
POC (poc_silva.py): 4-5 macro-tags (“Economia e Politica”, “Legislativo e Judiciario”, “Internacional”, “Tecnologia”, “Empresas Privadas”).
Sugestão: manter 8 tags; trazer o rigor de “allow list + reject list” do POC para a extração, mas mapeando para as 8 tags via o mapeamento determinístico já existente.
Filosofia de filtro na extração
Atual: PROMPT_EXTRACAO_PERMISSIVO_V8 é amplo e confia na sanitização posterior.
POC: lista de rejeição bem objetiva e bandas de score claras; em caso de dúvida, P3, mas aplicando um filtro mental mais pragmático.
Sugestão: “apertar” a extração no backend com:
Lista de rejeição mais concreta (do POC), explícita e curta.
Lista de interesse com exemplos “positivos/negativos”.
Faixas de score vinculadas a regras P1/P2/P3 obrigatórias.
Se não bate em allow list e não tem “assunto” do mapeamento, descarte (ou P3 com score ≤ 35 e sujeito ao gatekeeper).
Scoring e determinismo
Atual: bandas estão descritas, mas menos “operacionalizadas”.
POC: bandas muito claras e usadas em ranking/relatório; P1 >85, P2 50-84, P3 20-49 (exemplos consistentes).
Sugestão: impor validação no pipeline (ao receber do LLM) para ajustar scores incoerentes e rebater regras (ex.: RJ/Falência/M&A anunciado → força P1 e min_score 85).
Gatekeeper/sanitização
Atual: há PROMPT_SANITIZACAO_CLUSTER_V1 (ótimo), mas entra depois.
POC: filtra cedo pela extração (menos custo adiante).
Sugestão: endurecer a extração e manter o gatekeeper para clusters (segunda linha de defesa). Resulta em menos clusters “fracos”.
Agrupamento
Atual: prompts de agrupamento (em lote e incremental) ok; já existem práticas de chunking em process_articles.py.
POC: “Agrupamento Consolidado V2” com retry e fallback para singletons (bem pragmático).
Sugestão: harmonizar as diretrizes dos prompts de agrupamento para enfatizar:
Integridade total (NENHUMA notícia descartada).
Regras de “mesmo fato” e “estágios do mesmo processo” (POC traz bons exemplos).
Fallback automático (cada item vira grupo) quando JSON vem inválido do LLM (já há algo parecido — padronizar a instrução no prompt).
Resumos (tamanho por prioridade)
Atual: já existe diferenciação P1/P2/P3; ok.
POC: enfatiza 2 camadas (TOP críticos em 1 parágrafo, Radar/1 linha); objetivo idêntico.
Sugestão: manter, mas alinhar linguagem e exemplos ao POC (mais “bullet executivo” nos P3).
Campos/metadados
POC: capta url e trata jornal conforme a origem (PDF/JSON); alinha fontes para o relatório.
Atual: isso já existe no pipeline, mas garantir que a extração/normalização preserve url quando existir (especialmente nos JSONs de crawlers).
Sugestão: reforçar na instrução de extração a presença dos campos “informativos” (sem interferir no mapeamento de tags/prioridades).
Configuração de modelos e temperatura
POC: separa config de “decisão” (temp 0.1, top_p 0.95) de “texto” (temp ~0.3–0.5).
Atual: isso está em process_articles.py, mas nem sempre evidente.
Sugestão: padronizar doc/README e aplicar consistentemente: decisões (extração, gatekeeper, incremental) com temp baixa; textos (resumos) com temp um pouco maior.
Convergência proposta (sem mudar a taxonomia de 8 tags)
Fortalecer a extração (menos ruído):
Incorporar a “Lista de Rejeição” do POC, curta e objetiva, no PROMPT_EXTRACAO_PERMISSIVO_V8.
Trazer “Exemplos Positivos/Negativos” do POC dentro de cada tag temática (adaptados às 8 tags).
Enrijecer as bandas de score e o vínculo com prioridade (P1 ≥ 85, P2 50–84, P3 ≤ 49), com correções no pós-processamento (pipeline) quando vier incoerente.
Tornar explícito o “assunto-chave” determinístico:
Exigir que o LLM sempre preencha “assunto-chave” do guia (p.ex. “Recuperação Judicial”, “Decisão do CADE”, “M&A anunciado”), e derivar tag/prioridade a partir disso.
Se “assunto” não estiver no mapeamento determinístico, aplicar fallback: P3 com score baixo ou descarte (dependendo da presença/ausência em allow list).
Refinar agrupamento com as regras do POC:
Reforçar diretrizes: “estágios do mesmo processo”, “ações e consequências imediatas”.
Adicionar exemplos “bons” de mesmo evento e “maus” (parecidos, mas fato diferente) direto no prompt de agrupamento para tirar ambiguidade.
Gatekeeper pós-cluster
Manter PROMPT_SANITIZACAO_CLUSTER_V1 como segunda linha de defesa, porém com:
Instruções mais concisas (espelho da reject list de extração).
Resposta binária + justificativa curta (já é assim; bom).
Resumos
Harmonizar a retórica: P1 parágrafo rico, P2 parágrafo denso, P3 bullet one-liner começando pela entidade principal (padrão Radar do POC).
Config/tuning
Garantir temp baixa para etapas de decisão (0.1–0.2) e ligeiramente maior para resumo (0.3).
Aumentar robustez de JSON (já há extrair_json_da_resposta e correção no POC; manter).
Quadro de sugestões (o que mudar, impacto e complexidade)
Endurecer extração: allow list clara + reject list minimalista e objetiva
Tipo: ajuste de prompt
Impacto: alto (reduz ruído cedo)
Complexidade: baixa
Exigir “assunto-chave” e aplicar mapeamento determinístico (assunto ➜ prioridade e tag)
Tipo: ajuste de prompt + validação no pipeline (se vier incoerente, corrigir)
Impacto: alto (consistência total)
Complexidade: baixa/média
Vincular bandas de score a prioridades (hard rules) + coerção no pipeline
Tipo: ajuste de prompt + pós-processamento
Impacto: alto
Complexidade: média
Reforçar diretrizes de agrupamento com exemplos do POC (mesmo fato, estágios, ação⇄reação)
Tipo: ajuste de prompt
Impacto: médio/alto (clusters mais coesos)
Complexidade: baixa
Gatekeeper após cluster (texto mais objetivo, espelhando reject list)
Tipo: ajuste de prompt
Impacto: médio
Complexidade: baixa
Resumos P3 no formato “Radar” (one-liner com entidade no início)
Tipo: ajuste de prompt
Impacto: médio
Complexidade: baixa
Padronizar temperaturas/configs por etapa
Tipo: ajuste de config
Impacto: médio
Complexidade: baixa
Metadados (url/jornal/página/autor) garantidos na extração para JSON/PDF
Tipo: ajuste de instrução de extração + validação leve
Impacto: baixo/médio (melhora UX e rastreabilidade)
Complexidade: baixa
Plano por fases
Fase 1 (rápida: prompts + configs)
Atualizar PROMPT_EXTRACAO_PERMISSIVO_V8 com:
Reject list objetiva (POC)
Allow list por tag com exemplos positivos/negativos
Campo “assunto-chave” obrigatório
Bandas de score vinculadas à prioridade
Garantir temp baixa em extração/gatekeeper/agrupamento incremental e temp moderada nos resumos.
Fase 2 (pós-processamento/validação leve)
Validar coerência (assunto→tag/prioridade) e ajustar score mínimo por prioridade.
Se assunto não mapeia, P3 com score baixo ou descarte.
Fase 3 (agrupamento e gatekeeper)
Reforçar prompts de agrupamento com exemplos (mesmo fato/estágios/ação⇄reação).
Ajustar gatekeeper para ser binário e replicar reject list.
Fase 4 (UX/relato)
P3 com bullet “Radar” iniciando pela entidade principal no backend (para manter uniformidade com frontend).
Garantir metadados (url/jornal/página/autor) em todos os caminhos de ingestão.
Observações finais
Mantemos a decisão de usar 8 tags (fonte da verdade em backend/prompts.py), mas introduzimos a “disciplina pragmática” do poc_silva.py na extração e no score.
O conjunto de mudanças é majoritariamente em prompts e ajustes simples de validação; a estrutura de backend/front permanece.
Se fizer sentido, eu escrevo os rascunhos de prompts revisados já com a linguagem do POC (allow/reject, exemplos positivos/negativos, “assunto-chave” obrigatório e bandas de score), preservando as 8 tags atuais.

---

Casos práticos de ruído (observados hoje) e ajustes específicos

1) P1 indevido: “Idosa deve ser indenizada por queda em hotel” (cível de baixo valor)
- Problema: classificado como P1 e “Jurídico, Falências e Regulatório”.
- Ajuste proposto:
  - Nova regra de rejeição imediata: “Indenizações individuais cíveis ou trabalhistas de baixo valor, sem impacto corporativo/setorial ou mercado de capitais → IRRELEVANTE”.
  - Regra P1 dura: P1 só se o assunto-chave pertencer à lista crítica (RJ/Falência/M&A anunciado/Default/Crise de Liquidez/Quebra de Covenants/Decisão CADE com remédios). Casos fora dessa lista não podem ser P1.
  - Se o LLM retornar P1 fora da lista, o pipeline corrige para P3 ≤ 35 ou descarta (gatekeeper).

2) P1 indevido: “Auxiliar será indenizada por ofensas racistas” (trabalhista, dano moral)
- Problema: classificado como P1; irrelevante para Special Situations.
- Ajuste proposto:
  - Rejeição imediata: “Ações trabalhistas/indenizações individuais, sem relação com empresas listadas, RJ/Falência, M&A, default, NPLs, decisões do CADE → IRRELEVANTE”.
  - Reforçar “exemplos negativos” na allow list (POC) para afastar temas de direitos individuais sem efeito de mercado.

3) P1 indevido: “Fórum dos Leitores (opiniões/Cartas)”
- Problema: opinião/curadoria editorial → não é evento factual de negócio.
- Ajuste proposto:
  - Rejeição imediata: “Opinião/Cartas/Editorial/Crônicas/Colunas sem fato gerador objetivo → IRRELEVANTE”.
  - Se houver fato de negócio concreto dentro do texto, a extração deve recortar o fato; caso contrário, descartar.

4) P3 com tag errada: ‘Distressed Assets e NPLs’ aplicada a classificados/leilões genéricos
- Problema: cluster P3 rotulado como “Distressed Assets e NPLs” agregando avisos de licitações, leilões pequenos (veículos/joias/apartamentos isolados), chamadas de compras públicas etc.
- Ajuste proposto (tagging e gatekeeper):
  - Regra de default: “Classificados/Leilões genéricos/Chamadas públicas/Procurement” → IRRELEVANTE.
  - Exceções claras (podem ser ‘Distressed Assets e NPLs’ ou P1/P2 conforme o caso):
    - Leilão judicial de alto valor (> R$ 10 milhões) de ativos relevantes (imóveis corporativos, participações societárias, usinas, concessões).
    - Venda de carteira NPL (portfólio) ou anúncio de securitização de dívidas ativas por entes públicos (com valores e players).
    - Anúncio formal de desinvestimento corporativo (asset sale) por companhia relevante.
  - Exigir presença de: tipo (judicial/portfólio), valor/ordem de grandeza, atores corporativos ou ente público com potencial impacto. Sem isso → IRRELEVANTE.
  - Ajuste de mapeamento: “Leilão de apartamento individual”, “leilões de veículos/joias”, “editais de compra/serviços” → nunca mapear para ‘Distressed Assets e NPLs’. Se permanecer no corpus por algum motivo, rotular como IRRELEVANTE pelo gatekeeper.

Regras prontas para o prompt (copiar/colar nas seções de extração e gatekeeper)

- Rejeição Imediata (extração e gatekeeper):
  - Indenizações cíveis/trabalhistas individuais de baixo valor, sem impacto empresarial/setorial.
  - Opinião/Cartas/Editorial/Colunas sem fato gerador objetivo e verificável.
  - Classificados/leilões genéricos de bens de consumo, joias, veículos, apartamentos isolados e procurement comum (salvo exceções abaixo).
  - Crimes e segurança pública cotidiana; cultura/entretenimento sem tese de negócio; política partidária pura.

- Exceções (quando manter e como classificar):
  - Leilão judicial de alto valor (> R$ 10 milhões) ou venda de carteira NPL/Distressed → ‘Distressed Assets e NPLs’. Prioridade depende do tamanho/urgência; P1 se acionável/imediato e relevante.
  - Securitização de dívida ativa por estados/municípios (com valores/processos definidos) → ‘Dívida Ativa e Créditos Públicos’ (P1/P2 conforme materialidade/estágio).
  - Desinvestimento/asset sale corporativo, OPA, M&A anunciado → ‘M&A e Transações Corporativas’ (P1 por padrão se anunciado/formal).

- P1 – Regra Dura (gating):
  - Somente quando o “assunto-chave” ∈ {Recuperação Judicial, Falência, Pedido de Falência, Assembleia de Credores, Default de Dívida, Quebra de Covenants, Crise de Liquidez Aguda, M&A Anunciado, Decisão do CADE com remédios/efeitos vinculantes, Securitização relevante ou venda de carteira NPL de grande porte}.
  - Caso o LLM marque P1 fora dessa lista, normalizar para P3 (score ≤ 35) ou descartar, com justificativa do gatekeeper.

- Bandas de score vinculadas à prioridade (com coerção no pipeline):
  - P1 ≥ 85; P2 ∈ [50, 84]; P3 ∈ [20, 49].
  - RJ/Falência/M&A anunciado/Default não podem ter score < 85.
  - “Classificados/Procurement” nunca P1/P2.

- Campo obrigatório “assunto-chave” para derivação determinística:
  - O LLM deve sempre preencher o assunto exato (ex.: “Recuperação Judicial”, “Decisão do CADE”, “M&A anunciado”, “Venda de carteira NPL”, “Leilão judicial > R$10M”).
  - Derivar tag/prioridade via mapeamento; se não mapeia, classificar como IRRELEVANTE ou P3 ≤ 35 sujeito a gatekeeper.

Melhorias no texto dos P3 (Radar/one-liner)

- Padrão: “Entidade/Ator principal: ação/síntese em 1 linha; evitar listas massivas de itens sem relevância financeira.”
- Excluir do Radar: classificados/leilões genéricos, chamadas públicas, avisos de licitação comuns.
- Exemplo de reescrita (quando excepcionalmente mantido):
  - “Banco X: leilão judicial de portfólio de NPLs avaliado em R$ 120 mi — 1ª praça em 22/08; edital publicado.”
  - “Estado Y: securitização de dívida ativa (R$ 800 mi) — consulta pública aberta; leilão previsto para setembro.”

Heurísticas/keywords auxiliares

- Indicadores de irrelevância: “Fórum dos Leitores”, “Cartas do Leitor”, “indenização por danos morais” (sem empresa listada/impacto), “procurement”, “pregão eletrônico”, “chamada pública”, “edital de licitação”, “leilão de veículos/joias/apartamento”.
- Indicadores de relevância: “Recuperação Judicial”, “Falência”, “Pedido de Falência”, “default”, “quebra de covenants”, “M&A”, “OPA”, “Decisão do CADE”, “securitização”, “carteira NPL”, valores em R$ milhões/bilhões, players corporativos/governo.

Plano de rollout incremental (com esses casos em mente)

1. Endurecer EXTRAÇÃO com reject list, assunto-chave obrigatório e P1 gating.
2. Normalizar no pipeline scores incoerentes e derrubar P1 inválido.
3. Reforçar AGRUPAMENTO com exemplos “mesmo fato/estágios/ação⇄reação”; manter fallback.
4. Gatekeeper binário espelhando reject list; derrubar classificados/avisos e casos cíveis/trabalhistas individuais.
5. Radar: garantir one-liners de alto sinal; excluir ruído (classificados) por padrão.

---

Controle de volume por prioridade (sem sumir notícias)

- Metas diárias: P1 10–20; P2 10–40; P3 30–100.
- Princípio: nenhuma notícia some. Excesso desce de P1→P2 e de P2→P3; P3 excedente permanece visível (ou marcado como “extras”), nunca descartado.

Camada de capping com demotion ordenada
- Após agrupar e calcular score S (relevance + bônus/penalidades), ordenar clusters por S dentro de cada prioridade.
- Aplicar caps:
  - P1: se >20, demover os clusters de menor S para P2. Assuntos P1 “hard” (RJ/Falência/Default/OPA/CADE com remédios, NPL/securitização relevante) nunca caem abaixo de P2.
  - P2: se >40, demover os clusters de menor S para P3.
  - P3: se >100, manter excedentes visíveis (ou seção “extras”/paginação). Nunca ocultar definitivamente.

Agrupar mais para caber (reduzir cardinalidade sem perder fontes)
- Fusão por núcleo semântico: unir clusters com mesmo ator e fato temporal coincidente (anúncio+reação+análise no mesmo dia).
- Ação⇄consequência direta: decisão regulatória e reação de mercado no mesmo período (mesmo cluster).
- Preferir anexar em incremental: elevar o limiar de “preferir anexar” e, em caso de dúvida razoável, anexar.
- Passada de fusão antes do capping: checar P1/P2 do dia por tema_principal/ator e unir clusters quase-idênticos.