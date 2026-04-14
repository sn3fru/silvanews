# Problema de Agrupamento e Priorização de Notícias — BTG AlphaFeed

Este documento descreve em detalhes os **três grandes problemas** atuais do agrupamento (clusterização) e da priorização de notícias no BTG AlphaFeed, como a ferramenta trata cada um hoje, e toda a arquitetura e o fluxo necessários para propor e avaliar soluções melhores **sem alterar código ainda**. O objetivo é analisar o documento primeiro e só depois implementar mudanças.

---

## Parte A — Os três grandes problemas

### Problema 1: Não agrupar o que deveria ser agrupado

**Descrição:** Notícias que tratam do **mesmo fato gerador** (mesmo acontecimento, com diferentes pontos de vista, ângulos ou desdobramentos) acabam em clusters diferentes ou isoladas.

**Causa raiz (premissa errada):** O sistema tende a usar “textos parecidos” (similaridade semântica ou lexical) como condição para “tratar da mesma coisa”. Na prática:

- Dois textos podem ter **similaridade zero (ou quase zero) nas palavras** e ainda assim **relatarem o mesmo acontecimento**.
- Se o critério de agrupamento for principalmente vetorial ou por “semântica dos títulos”, essas notícias **não se agrupam**.

**Consequência:** Falso negativo — mesmo evento fragmentado em vários cards/dossiês, perdendo a visão consolidada que o usuário (executivo de Special Situations) precisa.

---

### Problema 2: Agrupar o que não deveria ser agrupado

**Descrição:** Notícias com **fatos geradores diferentes** (não são opiniões/ângulos diferentes do mesmo acontecimento) são colocadas no mesmo cluster.

**Pista importante (não certeza):** Um mesmo jornal normalmente **não publica duas matérias distintas sobre o mesmo fato** no mesmo dia. Se no mesmo cluster aparecem **várias notícias do mesmo jornal**, é um forte indício de que estamos agrupando fatos distintos. O **cenário ideal** é: **vários jornais** publicando suas notícias sobre o **mesmo fato** → aí sim faz sentido agrupar essas várias opiniões/notícias (uma de cada jornal, ou poucas por jornal quando for desdobramento explícito).

**Causa raiz:** Similaridade de domínio (economia, governo, tribunal, DF, etc.) ou de embedding arrasta para o mesmo cluster notícias que compartilham vocabulário/tema mas **não** o mesmo evento concreto.

**Consequência:** Falso positivo — dossiês inchados e incoerentes (ex.: cluster “BRB” com 18 notícias sobre BRB, Master, STF, carbono, Ibaneis, Cargill, etc.).

**Exemplos reais (resumo):**

- **Cluster “BRB: Risco de Intervenção e Busca por Soluções”** — 18 notícias agrupadas incluindo: STF créditos de carbono, propostas para salvar BRB (TCDF), Caixa federalização, DF capitalizar BRB, Caso Master, Fachin suspeição, Mendonça Master, STF fake news, Tereza Cristina chapa, Governo DF bancos BRB, EUA investigação Brasil, Imóvel Ibaneis, Flávio economia, Escalada inquietante, Cargill ataque hidrovias. Várias fontes repetidas (Valor, Estadão) com **múltiplos fatos** no mesmo cluster.

- **Cluster “TCU limita uso de créditos tributários”** — Resumo executivo correto (TCU, PGFN, transação tributária), mas **fontes originais** incluem: “Não é tão simples assim”, “trajetória do câmbio e inflação”, “País beneficiado pela tarifa de Trump”, “Nomad investimentos internacionais”, “Discurso para janeiro”, “Haddad renda básica”, “ALERTA”. Ou seja: **métrica de distância** aproximou textos que **não** são o mesmo fato gerador.

---

### Problema 3: Prioridade mal feita — passando muita coisa inútil para frente

**Descrição:** A classificação em P1 / P2 / P3 não reflete o que realmente importa para a mesa de Special Situations do BTG. Estamos **elevando demais** notícias que não impactam a operação.

**Definição desejada (a implementar/refinar):**

- **P1 (Crítico):** O que **realmente impacta** a vida no BTG / Special Situations de forma **drástica e imediata** — gatilhos acionáveis agora (RJ, default, M&A anunciado, intervenção BC, decisão vinculante STF/STJ em tributo/crédito, etc.).
- **P2 (Estratégico):** Também impacta a mesa, mas com **horizonte mais longo** — potencial de se tornar P1 ou movimentos estratégicos relevantes (dívida ativa, lei em votação, jurisprudência relevante, CVM/BC sancionador, etc.).
- **P3 (Monitoramento):** Notícias **grandes** em termos de mídia, mas **tangenciais** aos nossos temas — contexto macro, radar corporativo de empresas específicas, tecnologia/mercados adjacentes, atos de rotina. Não devem subir para P1/P2 só por serem “importantes” no sentido jornalístico.

**Causa raiz:** O prompt de classificação (Etapa 3) e/ou a consolidação (Etapa 4) não aplicam com rigor o “gating” P1/P2/P3; materialidade e “tese de investimento” não estão sendo usados de forma consistente para **rebaixar** o que é ruído para a mesa.

**Consequência:** Feed poluído com P1/P2 que não são acionáveis; desgaste de atenção e perda de confiança no filtro.

---

## Parte B — Objetivo do agrupamento e contexto de negócio

- **Agrupar notícias que tratam do MESMO FATO GERADOR:** mesmo acontecimento/evento, com diferentes pontos de vista ou ângulos (veículos diferentes, causa e consequência, reações, desdobramentos regulatórios), para formar **um único dossiê** e um resumo que pode contemplar múltiplos ângulos.
- **Contexto de negócio:** Mesa de **Special Situations do BTG**. A maioria das notícias (mortes, corrupção, guerra, etc.) é irrelevante; importam quando **nos tocam** — investimentos, oportunidades, mudanças de lei que nos impactam. Muitas mudanças de lei **não** nos afetam; é necessário senso crítico para relevância.
- **Qualidade > custo/latência:** Mesmo que o algoritmo fique mais lento, mais caro, mais complexo ou tenha etapas intermediárias, a prioridade é fazer agrupamento e priorização com qualidade.

---

## Parte C — Arquitetura da solução (trechos da documentação interna)

A documentação de referência está em **docs/SYSTEM.md**, **docs/OPERATIONS.md** e **.cursorrules**. Abaixo, trechos relevantes para entender onde cada decisão de agrupamento e priorização acontece.

### C.1 Stack e estrutura (SYSTEM.md)

```
Stack: Python 3.11, FastAPI, SQLAlchemy, PostgreSQL (pgvector), LangGraph, Gemini 2.0 Flash.

btg_alphafeed/
  backend/
    main.py              # FastAPI app (60+ endpoints, 10 background tasks)
    database.py          # ORM models (17 tabelas)
    crud.py              # 79 funcoes CRUD
    processing.py        # Pipeline v1 (embeddings, clusterizacao, resumo)
    prompts.py           # Fonte da verdade: tags, prioridades, 10+ prompts LLM
    ...
  process_articles.py   # Orquestrador v1 (31 funcoes, 4 etapas)
  load_news.py           # CLI ingestao
  run_complete_workflow.py  # Orquestrador: DB check -> load_news -> process_articles -> migrate
  migrate_incremental.py   # Sync incremental (18 tabelas)
```

### C.2 Banco de dados — tabelas core (SYSTEM.md)

**`artigos_brutos`** (ArtigoBruto):
- PK `id`; Unique `hash_unico`.
- Dados: `texto_bruto` (IMUTAVEL), `titulo_extraido`, `texto_processado`, `jornal`, `autor`, `pagina`, `data_publicacao`.
- Classificação: `tag`, `prioridade`, `categoria`, `relevance_score`, `relevance_reason`.
- Controle: `status` (pendente / pronto_agrupar / processado / irrelevante / erro), `tipo_fonte` (nacional/internacional).
- Embeddings: `embedding` (BYTEA 384d v1), `embedding_v2` (768d v2 — pgvector).
- FK: `cluster_id` -> clusters_eventos.

**`clusters_eventos`** (ClusterEvento):
- PK `id`.
- Dados: `titulo_cluster`, `resumo_cluster`, `tag`, `prioridade`, `total_artigos`.
- Controle: `status` (ativo/arquivado/descartado), `tipo_fonte`.
- Embedding: `embedding_medio` (BYTEA).
- Timestamps: `created_at`, `updated_at`, `ultima_atualizacao`.

### C.3 processing.py — funções de processamento (SYSTEM.md)

| Função | O que faz | Quem chama |
|--------|-----------|------------|
| `gerar_embedding(texto)` -> bytes | Embedding v1 384d (hash determinístico) | processar_artigo_pipeline, process_articles |
| `gerar_embedding_simples(texto)` -> bytes | Fallback: embedding baseado em hash | gerar_embedding |
| `gerar_embedding_v2(texto)` -> Optional[bytes] | v2.0 Embedding real 768d Gemini. Normalizado. | historian_node, backfill_graph |
| `bytes_to_embedding(bytes)` -> ndarray | Converte bytes para numpy array | find_or_create_cluster, process_articles, crud |
| `calcular_similaridade_cosseno(e1, e2)` -> float | Similaridade cosseno (0 a 1) | find_or_create_cluster, process_articles |
| `find_or_create_cluster(db, artigo, embedding, client)` -> int | Busca cluster por similaridade ou cria novo (threshold 0.7) | processar_artigo_pipeline |
| `processar_artigo_pipeline(db, id, client)` -> bool | Pipeline completo: analisa + cluster + embedding | main (background task) |
| `gerar_resumo_cluster(db, cluster_id, client)` -> bool | Gera resumo via LLM para cluster | main (background task) |

### C.4 Pipeline v1 — fluxo do main() (SYSTEM.md)

```
main()
  |
  +-> processar_artigos_pendentes(limite)   [modo incremental, default]
  |     |
  |     +-> ETAPA 1: processar_artigo_sem_cluster() x N  [parallel ThreadPool]
  |     |     Valida, extrai dados, gera embedding 384d, marca pronto_agrupar
  |     |     NAO usa LLM (economia de tokens)
  |     |
  |     +-> ETAPA 2: agrupar_noticias_incremental() OU agrupar_noticias_com_prompt()
  |     |     Separa por tipo_fonte -> processar_lote_incremental() por lote
  |     |     Prompt: PROMPT_AGRUPAMENTO_INCREMENTAL_V2 (incremental) ou PROMPT_AGRUPAMENTO_V1 (lote)
  |     |     Decisao: anexar a cluster existente OU criar novo
  |     |     -> marcar_artigos_processados()
  |     |
  |     +-> ETAPA 3: classificar_e_resumir_cluster() x N  [parallel ThreadPool]
  |     |     Prompt: PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 (unifica gatekeeper + resumo)
  |     |     Retorna: prioridade, tag, resumo
  |     |     -> _corrigir_tag_deterministica_cluster() (keywords hardcoded)
  |     |
  |     +-> ETAPA 4: consolidacao_final_clusters()
  |           Prompt: PROMPT_CONSOLIDACAO_CLUSTERS_V1
  |           Merge duplicados, soft delete, re-classifica se necessario
  |
  +-> V2 SHADOW MODE (se V2_SHADOW_MODE=1): workflow agentico (gatekeeper -> NER -> grafo -> historian -> writer)
```

**Constantes globais (process_articles.py):** `BATCH_SIZE_AGRUPAMENTO = 200`, `MAX_OUTPUT_TOKENS_STAGE2 = 32768`, `MAX_TRECHO_CHARS_STAGE2 = 120`. Modelo: `gemini-3-flash-preview`.

### C.5 Funções críticas do pipeline (SYSTEM.md)

| Função | Linhas (ref) | O que faz |
|--------|----------------|-----------|
| `processar_artigos_pendentes(limite)` | 558-759 | Orquestra 4 etapas |
| `processar_artigo_sem_cluster(db, id, client)` | 2075-2238 | Etapa 1: extrai dados, embedding, marca pronto_agrupar |
| `agrupar_noticias_incremental(db, client)` | 1359-1466 | Etapa 2: agrupa por tipo_fonte em lotes |
| `processar_lote_incremental(db, client, lote, clusters, n)` | 1484-1724 | Processa 1 lote incremental; usa PROMPT_AGRUPAMENTO_INCREMENTAL_V2 |
| `classificar_e_resumir_cluster(db, cluster_id, client, stats)` | 836-919 | Etapa 3: classifica+resume em 1 chamada LLM |
| `consolidacao_final_clusters(db, client)` | 955-1240 | Etapa 4: merge duplicados, PROMPT_CONSOLIDACAO_CLUSTERS_V1 |
| `_corrigir_tag_deterministica_cluster(db, cluster_id)` | 235-264 | Correção hardcoded por keywords (CDA, Dívida Ativa, Precatórios, FCVS) |

### C.6 Prompts ativos (SYSTEM.md)

| Variável | Etapa | Uso |
|----------|-------|-----|
| PROMPT_AGRUPAMENTO_V1 | 2 (lote) | Agrupar artigos em clusters (quando não há clusters no dia) |
| PROMPT_AGRUPAMENTO_INCREMENTAL_V2 | 2 (incremental) | Anexar a clusters existentes |
| PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 | 3 | Classifica + resume cluster (Gatekeeper V13 + resumo) |
| PROMPT_CONSOLIDACAO_CLUSTERS_V1 | 4 | Merge de clusters duplicados |
| PROMPT_DECISAO_CLUSTER_DETALHADO_V1 | (processing.py) | Decisão sim/não para anexar artigo a cluster (usado em find_or_create_cluster) |

**Tags:** 9 nacionais (TAGS_SPECIAL_SITUATIONS), 8 internacionais. Prioridades P1/P2/P3 definidas em listas editáveis (P1_ITENS, P2_ITENS, P3_ITENS) em prompts.py, possivelmente sobrescritas pelo banco (get_prompts_compilados).

### C.7 Workflow diário do usuário (SYSTEM.md / OPERATIONS.md)

O usuário cola PDFs em `../pdfs/` e executa **run_complete_workflow.py**:

1. **ETAPA 0:** check_and_start_local_db()
2. **PRE-STEP:** analyze_feedback.py — Feedback Learning (likes/dislikes → regras)
3. **ETAPA 1:** load_news.py --dir ../pdfs --direct --yes (ingestão)
4. **ETAPA 2:** process_articles.py (pipeline v1 + v2 integrado)
5. **ETAPA 3:** migrate_incremental --include-all (sync local -> Heroku)
6. **ETAPA 4/5:** notify_telegram, send_telegram (briefing)

**Execução manual (OPERATIONS.md):**
- `python process_articles.py` — pipeline completo
- `python process_articles.py --stage 4` — apenas etapa 4 (consolidação)
- `python process_articles.py --modo lote --stage all` — modo lote (reprocessamento total)
- `python reprocess_incremental_today.py` — reprocessar dia

### C.8 Endpoints relevantes (OPERATIONS.md)

- **POST /admin/processar-pendentes** — processa artigos pendentes (pode usar processar_artigo_background → processar_artigo_pipeline por artigo).
- **POST /api/admin/process-articles** — roda process_articles.py (processar_artigos_via_script).
- **GET /api/feed** — feed paginado (priority, tipo_fonte); clusters carregados por prioridade (P1, P2, P3).

---

## Parte D — Detalhes técnicos exaustivos

### D.1 Embeddings usados na clusterização

**Campo `artigos_brutos.embedding` (384d)**  
- Usado em: clusterização no script (modo lote por similaridade), `find_or_create_cluster`, cálculo de `embedding_medio` dos clusters.  
- Geração: `backend/processing.py` → `gerar_embedding(texto)` → na prática **`gerar_embedding_simples(texto)`**.  
- Implementação: MD5 do texto → seed para `np.random` → vetor 384d → normalização. **Não é embedding semântico real:** mesmo texto → mesmo vetor; texto diferente → vetor diferente (determinístico). Similaridade entre dois textos distintos não reflete significado.  
- Texto de entrada: `titulo + " " + texto_completo` (em processar_artigo_sem_cluster e processar_artigo_pipeline).

**Campo `artigos_brutos.embedding_v2` (768d)**  
- Geração: `gerar_embedding_v2(texto)` — API Gemini `models/gemini-embedding-001`, 768d, normalizado.  
- Uso: Graph-RAG v2, get_similar_articles_by_embedding, verificação de duplicata semântica. **Não é usado** na decisão de agrupamento da Etapa 2 do pipeline principal (dicas de similaridade desativadas).

### D.2 Agrupamento incremental (Etapa 2 — quando já existem clusters no dia)

- **Função:** `agrupar_noticias_incremental()` → `processar_lote_incremental()` (process_articles.py).  
- **Entrada ao LLM:**  
  - NOVAS_NOTICIAS: lista com `id` e `titulo` de cada notícia nova.  
  - CLUSTERS_EXISTENTES: para cada cluster, `cluster_id`, `tema_principal`, `titulos_internos` (até 10 títulos dos artigos do cluster).  
- **Saída esperada:** JSON com `tipo` (anexar / novo_cluster), `noticia_id`, `cluster_id_existente`, `tema_principal`.  
- **Trecho do código (process_articles.py, ~1562-1572):**

```text
# v2: Dicas de similaridade DESABILITADAS na ETAPA 2 (agrupamento incremental)
# MOTIVO: Embeddings de dominio (economia/governo/mercado) produzem falsos
# positivos com threshold < 0.92, levando o LLM a agrupar artigos com
# entidades em comum mas FATOS GERADORES diferentes (ex: "BRB+Master" com
# "Angra 3" porque ambos sao governo/economia).
# O agrupamento deve ser puramente baseado no julgamento do LLM sobre o
# FATO GERADOR, que era o comportamento correto da v1.
dicas_similaridade = ""
```

Ou seja: no fluxo incremental **não** se usa similaridade vetorial na decisão; só títulos e tema/títulos do cluster. O problema de agrupar demais pode vir do LLM (viés de “saga”/entidade) ou de outros fluxos.

### D.3 Agrupamento em lote por prompt (quando não há clusters no dia)

- **Função:** `agrupar_noticias_com_prompt()` (process_articles.py).  
- **Prompt:** PROMPT_AGRUPAMENTO_V1.  
- **Entrada por lote:** lista de notícias com `id`, `titulo`, `jornal`, `trecho` (texto_processado até MAX_TRECHO_CHARS_STAGE2 = 120 chars).  
- **Regras do prompt (resumo):** Regra da consequência (B por causa de A → mesmo grupo); Regra da saga (múltiplas pontas do mesmo problema → um dossiê); Radar corporativo; tema principal abrangente; integridade (todas alocadas); saída JSON com `tema_principal` e `ids_originais`.  
- Dicas de similaridade também desabilitadas neste fluxo.

### D.4 Agrupamento puro por similaridade (modo “lote” alternativo)

- **Função:** `agrupar_noticias_por_similaridade(db, artigos_processados)` (process_articles.py).  
- **Quando é usado:** apenas em `processar_artigos_em_lote()`: após processar cada artigo com processar_artigo_sem_cluster(), busca artigos com status `processado` e `processed_at >= hoje`, e chama esta função.  
- **Lógica:** Para cada artigo não visitado: inicia grupo; usa `artigo.embedding` (384d); para cada outro não visitado com **mesma tag** e com embedding, calcula similaridade cosseno; se **> 0.7** adiciona ao grupo e marca visitado. **Sem LLM.**

### D.5 find_or_create_cluster (processamento artigo a artigo via API)

- **Função:** `find_or_create_cluster(db, artigo_analisado, embedding_artigo, client)` (backend/processing.py).  
- **Chamada:** por `processar_artigo_pipeline()` após extração e `gerar_embedding(titulo + texto_completo)`.  
- **Fluxo:**  
  1. Busca clusters ativos do dia.  
  2. Filtra por mesma tag do artigo.  
  3. Para cada cluster com embedding_medio, calcula similaridade cosseno (artigo vs embedding_medio).  
  4. Escolhe cluster com maior similaridade.  
  5. Se melhor_similaridade **> 0.7**: chama LLM com PROMPT_DECISAO_CLUSTER_DETALHADO_V1 (decisão sim/não).  
  6. Se LLM “sim”: atualiza embedding_medio do cluster (média com embedding do artigo) e associa o artigo.  
  7. Caso contrário: cria novo cluster com _create_new_cluster().  
- **Prompt PROMPT_DECISAO_CLUSTER_DETALHADO_V1:** Recebe NOVA_NOTICIA (titulo, jornal, primeiros 1000 chars do texto) e CLUSTER_EXISTENTE (titulo_cluster, resumo_cluster, tag). Regras: mesmo fato gerador → agrupar; mesmo ator em contextos diferentes → não agrupar; consequência direta no mesmo período → pode agrupar; em dúvida razoável → preferir SIM. Resposta: SIM ou NÃO.

O pré-filtro é **sempre** por similaridade de embedding (0.7); o LLM só confirma. Se o centroide do cluster “puxar” muitos artigos por similaridade de domínio, o LLM pode confirmar agrupamentos errados.

### D.6 Atualização do embedding do cluster

Ao anexar um artigo em find_or_create_cluster:  
`embedding_medio_novo = np.mean([embedding_artigo, embedding_medio_antigo], axis=0)` e persiste em `clusters_eventos.embedding_medio`. O centroide muda a cada anexação; clusters podem “derivar” e atrair artigos de outro tema.

### D.7 Etapa 3 — Classificação e resumo (prioridade P1/P2/P3)

- **Função:** `classificar_e_resumir_cluster(db, cluster_id, client, stats)` (process_articles.py).  
- **Prompt:** PROMPT_ANALISE_E_SINTESE_CLUSTER_V1, com placeholders `P1_BULLETS`, `P2_BULLETS`, `P3_BULLETS`, `GUIA_TAGS_FORMATADO`.  
- **Entrada:** Payload com todos os artigos do cluster (id, titulo, texto_completo).  
- **Saída esperada:** JSON com `titulo`, `prioridade`, `tag`, `resumo_final`, `ids_artigos_utilizados`, `justificativa_saneamento`, `relevance_reason`.  
- **Injeção opcional:** get_feedback_rules() (regras aprendidas); get_context_for_cluster() (contexto histórico do grafo v2).  
- **Ação:** Atualiza cluster.titulo_cluster, cluster.prioridade, cluster.tag, cluster.resumo_cluster; commit.

**Listas de prioridade (prompts.py — P1_ITENS, P2_ITENS, P3_ITENS, usadas para gerar P1_BULLETS etc.):**

**P1_ITENS (exemplos):**  
Anúncio de Falência ou RJ de empresas Médias e Grandes; Default de Dívida, Calote ou Quebra de Covenants anunciado oficialmente; Crise de Liquidez Aguda em empresa listada ou emissora relevante; M&A ou Venda de Ativo > R$ 100 milhões — ANUNCIADO/ASSINADO; Leilões de Infraestrutura/Concessões > R$ 100 Mi com data marcada; Venda de carteiras NPLs/Distressed/Precatórios > R$ 50 Mi; Operação PF/MPF com busca e apreensão em Empresas Listadas ou Bancos; Decisões CADE bloqueando fusões ou remédios drásticos; Decisão STF/STJ com efeito VINCULANTE imediato em tributo ou recuperação de crédito; Intervenção ou Liquidação Extrajudicial de Instituição Financeira.

**P2_ITENS (exemplos):**  
Movimentação em Dívida Ativa/Créditos Podres; Lei/Regulação em fase final (Votação) com impacto em solvência setorial; Decisões TRFs/TJs com jurisprudência de impacto financeiro; Denúncia/Processo Sancionador CVM/BC; Suspensão judicial de M&A ou execução de dívidas; Resultados trimestrais com sinais graves de estresse; Investimento/CAPEX > R$ 1 bi privado ou capital misto; Disputas societárias em empresas relevantes; M&A Estratégico Tech/Energia/Saúde; Ativismo acionário agressivo; Rebaixamento de Rating.

**P3_ITENS (exemplos):**  
Tecnologia e mercados adjacentes (IA, defesa, gaming, cripto); Radar de empresas (Meta, Google, Apple, Tesla, etc.); Contexto macro e político (inflação, juros, câmbio, projetos de lei); Atos institucionais de rotina; Indicadores macro sem ruptura; Investimentos puramente estatais; Política fiscal em discussão inicial.

O prompt da Etapa 3 inclui regras de **rejeição** (conteúdo não jornalístico, ruído político, irrelevante, jurídico sem tese financeira, ruído corporativo de rotina) e **formatação por prioridade** (P1: resumo 5–8 linhas; P2: 3–5 linhas; P3: título + resumo em uma frase; IRRELEVANTE: título e resumo descrevendo rejeição).

### D.8 Etapa 4 — Consolidação

- **Função:** `consolidacao_final_clusters(db, client)` (process_articles.py).  
- **Prompt:** PROMPT_CONSOLIDACAO_CLUSTERS_V1.  
- **Regras (resumo):** Merge de clusters duplicados; rebaixamento de macro (déficit previdência, dívida estados, etc.) para P3 ou merge em “Radar Macroeconômico”; Radar Corporativo (unir “Empresa X faz A” e “Empresa X faz B” em um cluster); ao propor merge, escolher destino com prioridade mais alta; não criar novos clusters; ignorar IRRELEVANTE. Pode usar dicas de similaridade (embedding_v2) com threshold alto.

### D.9 Resumo dos caminhos de agrupamento

| Caminho | Onde | Decisão “pertence ao cluster” | Embedding |
|---------|------|-------------------------------|-----------|
| Pipeline principal — incremental | process_articles.py Etapa 2 | Só LLM (títulos + tema/títulos do cluster) | Nenhum (dicas desativadas) |
| Pipeline principal — lote (sem clusters no dia) | process_articles.py Etapa 2 | LLM (títulos + trechos) | Nenhum para decisão |
| processar_artigos_em_lote() | process_articles.py | Só similaridade cosseno > 0.7 + mesma tag | 384d (hash) em artigo.embedding |
| processar_artigo_pipeline (API) | backend/processing.py | Similaridade > 0.7 depois LLM (PROMPT_DECISAO_CLUSTER) | 384d (hash) |

---

## Parte E — Regras e constraints (não quebrar)

- **Gatekeeper V13:** encapsulado no PROMPT_ANALISE_E_SINTESE_CLUSTER_V1; não reescrever sem alinhamento.  
- **Nacional e internacional:** nunca misturar no mesmo cluster (`tipo_fonte` em artigos e clusters).  
- **texto_bruto:** somente leitura em artigos_brutos.  
- **v2:** rodar em shadow mode sem afetar v1.

---

## Parte F — O que NÃO fazer neste documento

- **Não** implementar ou editar solução no código.  
- **Não** propor um algoritmo específico aqui; o documento serve para analisar e **depois** sugerir métodos melhores (ex.: fato gerador explícito, uso de “vários jornais / mesmo fato” como sinal, NER + entidades + evento, duas etapas, gating P1/P2/P3 mais rígido).

---

## Parte G — Referências rápidas de arquivos

- **.cursorrules** — mapa de navegação; docs obrigatórios (SYSTEM.md, OPERATIONS.md).  
- **docs/SYSTEM.md** — pipeline v1 (4 etapas), funções críticas, tabelas, CRUD, prompts, deploy, migrate_incremental.  
- **docs/OPERATIONS.md** — setup, pipeline diário, migrate, endpoints (Feed, Admin, Settings, Prompts).  
- **backend/processing.py** — gerar_embedding, gerar_embedding_v2, find_or_create_cluster, calcular_similaridade_cosseno, processar_artigo_pipeline.  
- **backend/prompts.py** — PROMPT_AGRUPAMENTO_V1, PROMPT_AGRUPAMENTO_INCREMENTAL_V2, PROMPT_DECISAO_CLUSTER_DETALHADO_V1, PROMPT_ANALISE_E_SINTESE_CLUSTER_V1, P1_ITENS/P2_ITENS/P3_ITENS, GUIA_TAGS_FORMATADO.  
- **process_articles.py** — processar_artigo_sem_cluster, agrupar_noticias_incremental, processar_lote_incremental, agrupar_noticias_com_prompt, agrupar_noticias_por_similaridade, processar_artigos_em_lote, classificar_e_resumir_cluster, consolidacao_final_clusters, main().

Com isso, uma pessoa que leia **apenas este documento** tem contexto completo dos três problemas, dos exemplos reais, da pista “mesmo jornal vs vários jornais”, da definição desejada de P1/P2/P3, e de como a arquitetura e as funções funcionam hoje, podendo propor e discutir melhorias antes de qualquer alteração no código.

---

## Parte H — Soluções adotadas (implementação)

As melhorias abaixo foram implementadas conforme **docs/GUIA_IMPLEMENTACAO_AGRUPAMENTO_PRIORIZACAO.md** e **docs/TASK_IMPLEMENTACAO_AGRUPAMENTO_PRIORIZACAO.md**.

| Problema | Solução | Onde atua |
|----------|---------|-----------|
| **1 — Falsos negativos** | Extração de fato gerador na Etapa 1 (LLM + Pydantic FatoGeradorContract); Etapa 2 e API comparam por fato_gerador / fato_gerador_referente | processar_artigo_sem_cluster; processar_lote_incremental e agrupar_noticias_com_prompt; find_or_create_cluster |
| **2 — Falsos positivos** | Heurística da fonte (normalizar_jornal, FONTES_FLASHES); payload jornal e jornais_no_cluster; referente por qualidade (fato_gerador length >= 20) | utils.py; processar_lote_incremental; prompts incremental e V1; find_or_create_cluster |
| **3 — Priorização** | Multi-Agent Gating Etapa 3: Agente 1 (PROMPT_AGENTE_MATERIALIDADE_V1) + justificativa no classificador com default P3 | classificar_e_resumir_cluster |

- **Schema:** fato_gerador em artigos_brutos.metadados (JSON); nenhuma coluna nova. migrate_incremental inalterado.
- **Rollout:** mudanças ativas; feature flags opcionais (ex.: USE_FATO_GERADOR) em env se precisar reverter.
