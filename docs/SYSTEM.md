# BTG AlphaFeed - Referencia Completa do Sistema (v3.0 Multi-Tenant)

> Objetivo deste documento: Permitir que um LLM trace o caminho exato de implementacao de qualquer feature,
> sabendo quais arquivos, funcoes e tabelas precisara tocar, sem risco de ignorar checagens ou logicas ocultas.
>
> **Versao:** v3.0 Multi-Tenant Agentic | **Auth:** JWT (python-jose) | **Deploy:** Heroku + PostgreSQL

---

## 1. Stack e Estrutura de Pastas

**Stack**: Python 3.11, FastAPI, SQLAlchemy, PostgreSQL (pgvector), LangGraph, Gemini 2.0 Flash, HTML/CSS/JS estatico.

```
btg_alphafeed/
  backend/
    main.py              # FastAPI app (60+ endpoints, 10 background tasks)
    database.py          # ORM models (21+ tabelas)
    crud.py              # 79 funcoes CRUD
    processing.py        # Pipeline v1 (embeddings, clusterizacao, resumo)
    prompts.py           # Fonte da verdade: tags, prioridades, 10+ prompts LLM
    models.py            # Pydantic models (request/response)
    utils.py             # Utilidades (datas GMT-3, hashes, regex, Gemini helper)
    workflow.py          # v2.0 LangGraph StateGraph (5 nos)
    agents/
      __init__.py
      nodes.py           # v2.0 Nos agenticos (gatekeeper, NER, historian, writer)
      graph_crud.py      # v2.0 CRUD do grafo (Entity Resolution, queries temporais)
    collectors/
      file_loader.py     # FileLoader para PDFs/JSONs
  agents/estagiario/
    agent.py             # Agente de consulta (classificacao de intencao, sintese LLM)
    executor.py          # Executor ReAct (tool-calling, max 4 iteracoes)
    tools/definitions.py # Ferramentas: query_clusters, semantic_search
    tools/executor.py     # Registro e execucao de ferramentas
  agents/resumo_diario/
    agent.py             # Agente resumo: unificado (legado) + per-user PROMPT_MASTER_V2 (v4.0)
    tools/definitions.py # Tools: obter_textos_brutos_cluster, buscar_na_web (Tivaly)
  frontend/
    index.html + script.js   # Feed S.I.L.V.A. (~120 funcoes JS)
    settings.html + settings.js  # Admin (~80 funcoes JS)
    docs.html            # Documentacao renderer: Markdown + Mermaid
    login.html           # Login page with JWT auth
    style.css
  semantic_search/
    embedder.py, store.py, search.py, backfill_embeddings.py
  scripts/
    migrate_graph_tables.py  # v2.0 Migracao do grafo + prompt_configs
    backfill_graph.py        # v2.0 Backfill de entidades
    apply_graph_heroku.py    # v2.0 Migracao Heroku producao
    notify_telegram.py       # Notificacoes individuais Telegram
    analyze_feedback.py      # Feedback Learning: analisa likes/dislikes -> gera regras
  process_articles.py        # Orquestrador v1 (31 funcoes, 4 etapas)
  load_news.py               # CLI ingestao
  start_dev.py               # Servidor dev
  migrate_incremental.py     # Sync local -> Heroku
  send_telegram.py           # CLI Daily Briefing Telegram
```

---

## 2. Banco de Dados (21+ tabelas em `database.py`)

### Tabelas Core

**`artigos_brutos`** (ArtigoBruto) - Artigos ingeridos
- PK: `id` (int). Unique: `hash_unico` (str64).
- Dados: `texto_bruto` (IMUTAVEL), `titulo_extraido`, `texto_processado`, `jornal`, `autor`, `pagina`, `data_publicacao`
- Classificacao: `tag`, `prioridade`, `categoria`, `relevance_score`, `relevance_reason`
- Controle: `status` (pendente/pronto_agrupar/processado/irrelevante/erro), `tipo_fonte` (nacional/internacional)
- Embeddings: `embedding` (BYTEA 384d v1), `embedding_v2` (vector 768d v2 - pgvector)
- FK: `cluster_id` -> clusters_eventos
- JSON: `metadados` (flexivel, contem dados originais do JSON/PDF)
- Timestamps: `created_at`, `processed_at`
- Indices: hash, status+created, fonte+created, tag+prioridade, cluster+created

**`clusters_eventos`** (ClusterEvento) - Clusters de eventos
- PK: `id` (int).
- Dados: `titulo_cluster`, `resumo_cluster`, `tag`, `prioridade`, `total_artigos`
- Controle: `status` (ativo/arquivado/descartado), `tipo_fonte`
- Embedding: `embedding_medio` (BYTEA)
- Timestamps: `created_at`, `updated_at`, `ultima_atualizacao`
- Relationship: `artigos` (back_populates ArtigoBruto.cluster)

### Tabelas do Grafo v2.0

**`graph_entities`** (GraphEntity) - Nos do Grafo de Conhecimento
- PK: `id` (UUID). Unique constraint: `(canonical_name, entity_type)`
- Dados: `name` (original), `canonical_name` (normalizado), `entity_type` (PERSON/ORG/GOV/EVENT/CONCEPT)
- Extra: `description`, `aliases` (JSONB list)
- Indice trigram: `gin(canonical_name gin_trgm_ops)` para busca fuzzy

**`graph_edges`** (GraphEdge) - Arestas Artigo <-> Entidade
- PK: `id` (int). Unique: `(artigo_id, entity_id)`
- FK: `artigo_id` -> artigos_brutos (CASCADE), `entity_id` -> graph_entities (CASCADE)
- Dados: `relation_type` (PROTAGONIST/TARGET/MENTIONED/COADJUVANT), `sentiment_score` (-1 a 1), `context_snippet`, `confidence` (0-1)

### Tabelas de Chat e Agente

| Tabela | Descricao | FKs |
|---|---|---|
| `chat_sessions` | Sessoes de chat por cluster | cluster_id -> clusters_eventos |
| `chat_messages` | Mensagens de chat | session_id -> chat_sessions |
| `estagiario_chat_sessions` | Sessoes do agente por dia | (nenhuma FK) |
| `estagiario_chat_messages` | Mensagens do agente | session_id -> estagiario_chat_sessions |

### Tabelas de Configuracao

| Tabela | Descricao |
|---|---|
| `prompt_tags` (PromptTag) | Tags configuraveis (nome, descricao, exemplos, ordem, tipo_fonte) |
| `prompt_prioridade_itens` (PromptPrioridadeItem) | Itens de prioridade (nivel, texto, ordem, tipo_fonte) |
| `prompt_templates` (PromptTemplate) | Templates de prompt (chave unica, conteudo) |
| `prompt_configs` (PromptConfig) | Configs dinamicas de prompt (ex: FEEDBACK_RULES). Feedback Learning System |
| `configuracoes_coleta` (ConfiguracaoColeta) | Configs de coletores (telegram, web_crawler) |

### Outras Tabelas

| Tabela | Descricao |
|---|---|
| `sinteses_executivas` | Sinteses diarias (metricas do dia) |
| `logs_processamento` | Logs (nivel, componente, mensagem, detalhes JSON) |
| `feedback_noticias` | Like/dislike por artigo (artigo_id, feedback, processed) |
| `cluster_alteracoes` | Auditoria (campo_alterado, valor_anterior, valor_novo, motivo, usuario) |
| `semantic_embeddings` | Embeddings dedicados OpenAI (vector_bytes, dimension, provider, model) |
| `deep_research_jobs` | Pesquisas profundas async (cluster_id, status, result_json) |
| `social_research_jobs` | Pesquisas sociais async (cluster_id, status, result_json) |

### Tabelas Multi-Tenant v3.0

| Tabela | Descricao | FKs |
|---|---|---|
| **`usuarios`** (Usuario) | Usuarios da plataforma: `id`, `nome`, `email`, `senha_hash`, `role` (admin\|user), `ativo`, timestamps. Relationships: preferencias (1:1), resumos (1:N) | - |
| **`preferencias_usuario`** (PreferenciaUsuario) | Preferencias por usuario: `id`, `user_id` (FK usuarios), `tags_interesse`, `tags_ignoradas`, `fontes_ignoradas` (JSON), `prioridade_minima`, `tipo_fonte_preferido`, `tamanho_resumo` (curto\|medio\|longo), `template_resumo_id` (FK templates), `config_extra` (JSON), timestamps | user_id -> usuarios, template_resumo_id -> templates_resumo_usuario |
| **`templates_resumo_usuario`** (TemplateResumoUsuario) | Templates reutilizaveis: `id`, `nome`, `descricao`, `system_prompt`, `criado_por` (FK usuarios), `is_public`, timestamps | criado_por -> usuarios |
| **`resumos_usuario`** (ResumoUsuario) | Resumos diarios por usuario: `id`, `user_id` (FK), `data_referencia`, `template_id` (FK), `clusters_avaliados` (JSON), `clusters_escolhidos` (JSON), `texto`, `texto_whatsapp`, `prompt_version`, `metadados` (JSON), timestamps | user_id -> usuarios, template_id -> templates_resumo_usuario |

---

## 3. CRUD (`crud.py` - 79 funcoes)

### Artigos (12 funcoes)

| Funcao | O que faz | Tabelas |
|---|---|---|
| `get_artigo_by_hash(db, hash_unico)` | Busca por hash unico | ArtigoBruto |
| `get_artigo_by_id(db, id_artigo)` | Busca por ID | ArtigoBruto |
| `create_artigo_bruto(db, artigo_data)` | Cria artigo bruto | ArtigoBruto |
| `update_artigo_processado(db, id, dados, embedding)` | Atualiza dados + status='processado' | ArtigoBruto |
| `update_artigo_dados_sem_status(db, id, dados, embedding)` | Atualiza dados SEM mudar status | ArtigoBruto |
| `update_artigo_status(db, id, status)` | Muda apenas status | ArtigoBruto |
| `get_artigos_pendentes(db, limite, day_str)` | Lista pendentes do dia | ArtigoBruto |
| `get_artigos_by_cluster(db, cluster_id)` | Artigos de um cluster | ArtigoBruto |
| `get_artigos_processados_hoje(db)` | Processados hoje sem cluster | ArtigoBruto |
| `list_sourcers_by_date_and_tipo(db, date, tipo)` | Lista fontes com contagem | ArtigoBruto |
| `list_raw_articles_by_source_date_tipo(db, source, date, tipo)` | Artigos brutos por fonte | ArtigoBruto |
| `get_textos_brutos_por_cluster_id(db, cluster_id)` | Textos brutos de um cluster | ArtigoBruto |

### Clusters (20 funcoes)

| Funcao | O que faz | Tabelas |
|---|---|---|
| `get_active_clusters_today(db)` | Clusters ativos de hoje | ClusterEvento |
| `get_cluster_by_id(db, cluster_id)` | Busca cluster por ID | ClusterEvento |
| `create_cluster(db, cluster_data)` | Cria cluster (verifica duplicata por titulo+tag) | ClusterEvento |
| `associate_artigo_to_cluster(db, id_artigo, id_cluster)` | Associa artigo + atualiza total_artigos | ArtigoBruto, ClusterEvento |
| `update_cluster_embedding(db, id_cluster, embedding)` | Atualiza embedding medio | ClusterEvento |
| `get_clusters_for_feed(db, data_inicio)` | Feed simples | ClusterEvento, ArtigoBruto |
| `get_clusters_for_feed_by_date(db, date, page, size, priority, tipo_fonte)` | Feed paginado com feedback | ClusterEvento, ArtigoBruto, FeedbackNoticia |
| `get_cluster_details_by_id(db, cluster_id)` | Detalhes completos (lazy load) | ClusterEvento, ArtigoBruto |
| `get_cluster_com_artigos(db, cluster_id)` | Cluster + artigos para analise | ClusterEvento, ArtigoBruto |
| `get_clusters_existentes_hoje(db)` | Todos os clusters de hoje | ClusterEvento |
| `create_cluster_for_artigo(db, artigo, tema)` | Cria cluster para 1 artigo | ClusterEvento, ArtigoBruto |
| `update_cluster_priority(db, id, nova, motivo)` | Atualiza prioridade + registra alteracao | ClusterEvento, ClusterAlteracao |
| `update_cluster_tags(db, id, novas, motivo)` | Atualiza tags + registra alteracao | ClusterEvento, ClusterAlteracao |
| `update_cluster_title(db, id, novo, motivo)` | Atualiza titulo + registra alteracao | ClusterEvento, ClusterAlteracao |
| `soft_delete_cluster(db, id, motivo)` | Arquiva cluster (status=descartado) | ClusterEvento, ClusterAlteracao |
| `merge_clusters(db, destino_id, fontes_ids, ...)` | Consolida clusters (move artigos, soft delete fontes) | ClusterEvento, ArtigoBruto, ClusterAlteracao |
| `get_cluster_alteracoes(db, cluster_id)` | Historico de alteracoes | ClusterAlteracao |
| `get_all_cluster_alteracoes(db, limit)` | Todas alteracoes recentes | ClusterAlteracao |
| `get_cluster_counts_by_date_and_tipo_fonte(db, date)` | Contadores por aba | ClusterEvento |
| `associate_artigo_to_existing_cluster(db, id, cluster_id)` | Wrapper de associate_artigo_to_cluster | ArtigoBruto, ClusterEvento |

### Metricas, BI e Feedback (11 funcoes)

| Funcao | O que faz |
|---|---|
| `get_metricas_today(db)` / `get_metricas_by_date(db, date)` | Metricas do dia (coletadas, eventos, fontes, por prioridade) |
| `get_sintese_today(db)` / `get_sintese_by_date(db, date)` / `create_or_update_sintese(db, ...)` | Sintese executiva diaria |
| `agg_noticias_por_dia(db, dias)` | Serie temporal (N dias) |
| `agg_noticias_por_fonte(db, limit)` / `agg_noticias_por_autor(db, limit)` | Rankings |
| `agg_estatisticas_gerais(db)` / `agg_noticias_por_tag(db)` / `agg_noticias_por_prioridade(db)` | Estatisticas gerais |
| `create_feedback(db, artigo_id, feedback)` / `list_feedback(db, ...)` / `mark_feedback_processed(db, id)` | Feedback CRUD |

### Chat, Estagiario, Logs (8 funcoes)

| Funcao | O que faz |
|---|---|
| `get_or_create_chat_session(db, cluster_id)` | Sessao de chat por cluster |
| `add_chat_message(db, session_id, role, content)` | Mensagem de chat |
| `get_chat_messages_by_session(db, session_id)` / `get_chat_session_by_cluster(db, cluster_id)` | Consultas de chat |
| `create_estagiario_session(db, date)` / `add_estagiario_message(db, ...)` / `list_estagiario_messages(db, ...)` | Chat do agente |
| `create_log(db, nivel, componente, mensagem, detalhes, artigo_id, cluster_id)` | Log de processamento |

### Prompts Configuraveis (15 funcoes)

| Funcao | O que faz |
|---|---|
| `list_prompt_tags(db, tipo_fonte)` / `create_prompt_tag(db, ...)` / `update_prompt_tag(db, ...)` / `delete_prompt_tag(db, ...)` | CRUD Tags |
| `list_prompt_prioridade_itens_grouped(db, tipo_fonte)` / `create_prompt_prioridade_item(db, ...)` / `update_prompt_prioridade_item(db, ...)` / `delete_prompt_prioridade_item(db, ...)` | CRUD Prioridades |
| `list_prompt_templates(db)` / `upsert_prompt_template(db, ...)` / `delete_prompt_template(db, ...)` | CRUD Templates |
| `get_prompts_compilados(db)` | Retorna tags+prioridades formatados para prompts.py |
| `get_database_stats(db)` | Estatisticas gerais do banco |

### Research Jobs (8 funcoes)

| Funcao | O que faz |
|---|---|
| `create_deep_research_job` / `update_deep_research_job` / `get_deep_research_job` / `list_deep_research_jobs_by_cluster` | Deep Research CRUD |
| `create_social_research_job` / `update_social_research_job` / `get_social_research_job` / `list_social_research_jobs_by_cluster` | Social Research CRUD |

---

## 4. Utilidades (`utils.py` - 25 funcoes, `processing.py` - 11 funcoes)

### utils.py - Funcoes Essenciais

| Funcao | O que faz | Quem chama |
|---|---|---|
| `corrigir_tag_invalida(tag)` | Mapeia tags invalidas/similares para TAGS_SPECIAL_SITUATIONS | process_articles, processing, agents |
| `corrigir_prioridade_invalida(prioridade)` | Normaliza prioridade; retorna IRRELEVANTE se invalida | process_articles, processing, crud |
| `extrair_json_da_resposta(resposta)` | Extrai JSON de resposta LLM com 5+ fallbacks | process_articles, agents, main |
| `gerar_titulo_fallback_curto(texto, max_palavras=10)` | Gera titulo deterministico quando falta titulo | process_articles, file_loader |
| `titulo_e_generico(titulo)` | Detecta titulos genericos (nao usaveis para agrupamento) | process_articles, file_loader |
| `normalizar_jornal(nome)` | Chave canonica do jornal (lowercase, sem acentos, aliases). Usado na heuristica da fonte no agrupamento | process_articles, processing (Task 1) |
| `inferir_tipo_fonte_por_jornal(nome_jornal)` | Infere nacional/internacional pelo nome do jornal | process_articles, main, file_loader |
| **Constante** `FONTES_FLASHES` | Lista de jornais que emitem flashes; prompt de agrupamento mais rigoroso para estas fontes | prompts, process_articles (Task 1) |
| **Etapa 1 — Fato gerador** | `processar_artigo_sem_cluster`: após validação Noticia, chama LLM com PROMPT_EXTRACAO_FATO_GERADOR_V1; valida com FatoGeradorContract; grava em `metadados['fato_gerador']`. Falha em artigos novos = reprocesso (sem fallback titulo); artigos já processados = fallback titulo até backfill (Task 3) | process_articles |
| `migrar_noticia_cache_legado(noticia_data)` | Migra formato legado para formato atual | process_articles, processing |
| `gerar_hash_unico(texto, url)` | SHA256 para deduplicacao de artigos | main |
| `eh_lixo_publicitario(titulo, texto)` | Detecta conteudo publicitario (desabilitada) | - |
| `get_gemini_model()` | Configura e retorna modelo Gemini (singleton) | main, agents, backfill |

### utils.py - Datas GMT-3 (Sao Paulo)

| Funcao | O que faz |
|---|---|
| `get_date_brasil()` -> `date` | Data atual em GMT-3 |
| `get_date_brasil_str()` -> `str` | Data YYYY-MM-DD em GMT-3 |
| `get_datetime_brasil()` -> `datetime` | Datetime atual em GMT-3 |
| `get_datetime_brasil_str()` -> `str` | Datetime ISO em GMT-3 |
| `parse_date_brasil(date_str)` -> `date` | Converte string para date (GMT-3) |
| `convert_to_brasil_tz(dt)` -> `datetime` | Converte datetime para GMT-3 |

**IMPORTANTE**: `SAO_PAULO_TZ = timezone(timedelta(hours=-3))`. Todo o sistema usa GMT-3. Nunca use UTC direto.

### processing.py - Funcoes de Processamento

| Funcao | O que faz | Quem chama |
|---|---|---|
| `gerar_embedding(texto)` -> bytes | Embedding v1 384d (hash deterministico) | processar_artigo_pipeline, process_articles |
| `gerar_embedding_simples(texto)` -> bytes | Fallback: embedding baseado em hash SHA256 | gerar_embedding |
| `gerar_embedding_v2(texto)` -> Optional[bytes] | **v2.0** Embedding real 768d via Gemini `text-embedding-004`. Normalizado. | historian_node, backfill_graph |
| `cosine_similarity_bytes(a, b)` -> float | Similaridade cosseno entre dois BYTEA embeddings | graph_crud (busca vetorial) |
| `bytes_to_embedding(bytes)` -> ndarray | Converte bytes para numpy array | find_or_create_cluster, process_articles, crud |
| `calcular_similaridade_cosseno(e1, e2)` -> float | Similaridade cosseno (0 a 1) | find_or_create_cluster, process_articles |
| `find_or_create_cluster(db, artigo, embedding, client)` -> int | Busca cluster por similaridade ou cria novo (threshold 0.7) | processar_artigo_pipeline |
| `processar_artigo_pipeline(db, id, client)` -> bool | Pipeline completo: analisa + cluster + embedding | main (background task) |
| `gerar_resumo_cluster(db, cluster_id, client)` -> bool | Gera resumo via LLM para cluster | main (background task) |
| `inicializar_processamento()` | Inicializa sistema de processamento | main (lifespan) |

---

## 5. Pipeline v1 (`process_articles.py` - 31 funcoes, orquestrador principal)

### Constantes Globais
- `BATCH_SIZE_AGRUPAMENTO = 200`, `MAX_OUTPUT_TOKENS_STAGE2 = 32768`, `MAX_TRECHO_CHARS_STAGE2 = 120`
- Gemini model: `gemini-2.5-flash` (configurado via `GEMINI_API_KEY`)

### Fluxo do `main()` (flags: `--stage`, `--modo`, `--limite`)

```
main()
  |
  +-> processar_artigos_pendentes(limite)   [incremental mode, default]
  |     |
  |     +-> ETAPA 1: processar_artigo_sem_cluster() x N  [parallel ThreadPool]
  |     |     Valida, extrai dados, gera embedding 384d, marca pronto_agrupar
  |     |     NAO usa LLM (economia de tokens)
  |     |
  |     +-> ETAPA 2: agrupar_noticias_incremental()
  |     |     Separa por tipo_fonte -> processar_lote_incremental() por lote
  |     |     Prompt: PROMPT_AGRUPAMENTO_INCREMENTAL_V2
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
  +-> V2 SHADOW MODE (se V2_SHADOW_MODE=1)
        Import: backend.workflow.run_batch_workflow
        Busca TODOS artigos processados hoje (sem limite)
        Roda workflow agentico (gatekeeper -> NER -> grafo -> historian(embed+RAG) -> writer)
        shadow_mode=True: salva metadados v2 em artigo.metadados (v2_resumo, v2_entities, etc.)
```

### Funcoes Criticas (que um LLM PRECISA saber)

| Funcao | Linhas | O que faz | Chamadas backend |
|---|---|---|---|
| `processar_artigos_pendentes(limite)` | 558-759 | Orquestra 4 etapas | get_artigos_pendentes, processar_artigo_sem_cluster, agrupar_noticias_incremental, classificar_e_resumir_cluster, consolidacao_final_clusters |
| `processar_artigo_sem_cluster(db, id, client)` | 2075-2238 | Etapa 1: extrai dados, embedding, marca pronto_agrupar | update_artigo_dados_sem_status, gerar_embedding, create_log |
| `agrupar_noticias_incremental(db, client)` | 1359-1466 | Etapa 2: agrupa por tipo_fonte em lotes | processar_lote_incremental, marcar_artigos_processados |
| `processar_lote_incremental(db, client, lote, clusters, n)` | 1484-1724 | Processa 1 lote incremental | associate_artigo_to_cluster, create_cluster, PROMPT_AGRUPAMENTO_INCREMENTAL_V2 |
| `classificar_e_resumir_cluster(db, cluster_id, client, stats)` | 836-919 | Etapa 3: Agente 1 (materialidade) + classifica+resume (PROMPT_ANALISE_E_SINTESE_CLUSTER_V1) | get_cluster_by_id, get_artigos_by_cluster, PROMPT_AGENTE_MATERIALIDADE_V1, PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 |
| `consolidacao_final_clusters(db, client)` | 955-1240 | Etapa 4: merge duplicados | merge_clusters, update_cluster_title, PROMPT_CONSOLIDACAO_CLUSTERS_V1 |
| `_corrigir_tag_deterministica_cluster(db, cluster_id)` | 235-264 | Correcao hardcoded por keywords (CDA, Divida Ativa, Precatorios, FCVS) | get_cluster_by_id, get_artigos_by_cluster |
| `extrair_json_da_resposta(resposta)` | 100-159 | Extrai JSON do LLM com 5 estrategias de fallback | (nenhuma) |
| `mapear_tag_prompt_para_modelo(tag, tipo)` | 761-796 | Normaliza tag do LLM para tag canonica | corrigir_tag_invalida |

---

## 6. Pipeline v2 Graph-RAG (`workflow.py` + `backend/agents/`)

### Fluxo LangGraph

```
FeedState (TypedDict com 15 campos)
  |
  gatekeeper_node      -> Regex hard filter (8 padroes) + qualidade (>50 chars)
  | [relevant?]
  entity_extraction_node -> NER via Gemini Flash (PROMPT_ENTITY_EXTRACTION, max 15 entidades)
  |
  entity_resolution_node -> Resolve nomes: KNOWN_ALIASES dict -> busca exata -> busca fuzzy pg_trgm
  |                         Persiste: get_or_create_entity() + create_edge()
  historian_node         -> 3 etapas: (A) gerar_embedding_v2() Gemini 768d -> salva embedding_v2
  |                         (B) get_historical_context_for_entities(): SQL temporal 7 dias por PROTAGONIST/TARGET
  |                         (C) get_similar_articles_by_embedding(): busca vetorial cosine 30 dias
  |
  writer_node            -> PROMPT_RESUMO_COM_CONTEXTO: {texto} + {contexto_historico} + {prioridade P1/P2/P3}
```

### Entity Resolution e Busca (`graph_crud.py`)

- `KNOWN_ALIASES`: Dict com ~40 entradas (Lula, Haddad, Petrobras, BC, CVM, STF, etc.)
- `_normalize_name()`: Lowercase + remove acentos + remove pontuacao
- `resolve_canonical_name()`: KNOWN_ALIASES lookup -> fallback title case
- `find_entity_by_name()`: Busca exata canonical -> busca exata name -> busca fuzzy pg_trgm (threshold 0.6)
- `get_or_create_entity()`: Find or create + atualiza aliases se nome diferente
- `link_artigo_to_entities(db, artigo_id, entities)`: Resolve + persiste lista de entidades -> retorna edges
- `get_historical_context_for_entities()`: Busca SQL temporal - clusters recentes por entidade PROTAGONIST/TARGET
- `get_similar_articles_by_embedding(db, embedding_bytes, days, top_k)`: **Busca vetorial** - carrega embeddings_v2 recentes, calcula cosine similarity em Python, retorna top_k similares (threshold 0.7)
- `get_vector_context_for_article(db, embedding_bytes, artigo_id)`: Wrapper que busca artigos similares e monta contexto textual com resumos dos clusters associados
- `get_entity_stats(db)`: Estatisticas do grafo (total entidades/arestas, por tipo/relacao)

---

## 7. Prompts (`prompts.py`)

### Tags Nacionais (`TAGS_SPECIAL_SITUATIONS` - 9 categorias)
M&A e Transacoes Corporativas | Juridico, Falencias e Regulatorio | Divida Ativa e Creditos Publicos | Distressed Assets e NPLs | Mercado de Capitais e Financas Corporativas | Politica Economica (Brasil) | Infraestrutura e Concessoes | Agro e Commodities | Imobiliario e Fundos

### Tags Internacionais (`TAGS_SPECIAL_SITUATIONS_INTERNACIONAL` - 8 categorias)
Global M&A | Global Legal and Regulatory | Sovereign Debt and Credit | Global Distressed | Global Capital Markets | Central Banks | Geopolitics and Trade | Technology and Innovation

### Prompts Ativos no Pipeline

| Variavel | Etapa | Uso |
|---|---|---|
| `PROMPT_EXTRACAO_PDF_RAW_V1` | Ingestao | Extrair texto de PDFs (sem resumir) |
| `PROMPT_AGRUPAMENTO_V1` | 2 (lote) | Agrupar artigos em clusters |
| `PROMPT_AGRUPAMENTO_INCREMENTAL_V2` | 2 (incremental) | Anexar a clusters existentes |
| `PROMPT_EXTRACAO_FATO_GERADOR_V1` | Etapa 1 | Extrai fato_gerador (FatoGeradorContract); processar_artigo_sem_cluster |
| `PROMPT_AGENTE_MATERIALIDADE_V1` | 3 | Agente 1 (Advogado do Diabo): deve_ser_p3 + justificativa; injetado antes do classificador |
| `PROMPT_ANALISE_E_SINTESE_CLUSTER_V1` | 3 | Classifica+resume cluster (substitui Gatekeeper V13 + Resumo V3) |
| `PROMPT_CONSOLIDACAO_CLUSTERS_V1` | 4 | Merge de clusters duplicados |
| `PROMPT_RESUMO_EXPANDIDO_V1` / `_FALLBACK` | On-demand | Resumo expandido (deep-dive) |
| `PROMPT_CHAT_CLUSTER_V1` | Chat | Chat contextual com cluster |
| `PROMPT_ENTITY_EXTRACTION` | v2 No 2 | NER para o grafo |
| `PROMPT_RESUMO_COM_CONTEXTO` | v2 No 5 | Resumo com historico |
| `PROMPT_TELEGRAM_BRIEFING_V1` | Briefing | Daily Briefing HTML para Telegram (Morning Call) |
| `PROMPT_MASTER_V2` | Resumo per-user (v4.0) | Chassis imutavel + slots personalizaveis. Secoes: foco_analista, distressed, estrategico, regulatorio, internacional |
| `PROMPT_RESUMO_UNIFICADO_V1` | Resumo unificado (batch) | 1 chamada LLM, 3 secoes fixas (distressed, regulatorio, estrategico, geral) |

**NOTA**: `PROMPT_EXTRACAO_PERMISSIVO_V8`, `PROMPT_EXTRACAO_JSON_V1` e `PROMPT_RESUMO_FINAL_V3` sao ALIASES de `PROMPT_ANALISE_E_SINTESE_CLUSTER_V1`.

### Funcoes de Prompt Dinamico

| Funcao | O que faz | Chamada por |
|---|---|---|
| `get_feedback_rules()` | Carrega REGRAS_APRENDIDAS de `prompt_configs` (cache 10min, flag `FEEDBACK_RULES_ENABLED`) | Etapa 3 (sintese), Etapa 4 (consolidacao) |

---

## 8. Backend API (`main.py` - 60+ endpoints)

### Estado Global
- `upload_progress = {}` - Progresso de uploads (file_id -> status/progress/message)
- `processing_state = {}` - Estado do processamento de artigos

### Endpoints por Categoria

**Feed (6)**: GET `/api/feed` (paginado, filtros priority+tipo_fonte) | GET `/api/cluster/{id}` | GET `/api/cluster/{id}/artigos` | POST `/api/clusters/{id}/expandir-resumo` | GET `/api/contadores_abas` | GET `/api/sourcers`

**Admin (8)**: POST `/admin/processar-pendentes` | POST `/api/admin/upload-file` | GET `/api/admin/upload-progress/{id}` | POST `/api/admin/process-articles` | GET `/api/admin/processing-status` | POST `/admin/gerar-resumo/{id}` | POST `/admin/carregar-arquivos` | GET `/admin/stats`

**Settings CRUD (12)**: GET/PUT/DELETE para `/api/settings/artigos`, `/clusters`, `/sinteses` (com paginacao e filtros)

**Prompts (11)**: CRUD completo para `/api/prompts/tags`, `/prioridades`, `/templates` + GET `/api/prompts/compilados`

**Chat (2)**: POST `/api/chat/send` | GET `/api/chat/{cluster_id}/messages`

**Estagiario (3)**: POST `/api/estagiario/start` | POST `/api/estagiario/send` | GET `/api/estagiario/messages/{id}`

**BI (6)**: GET `/api/bi/series-por-dia` | `/noticias-por-fonte` | `/noticias-por-autor` | `/estatisticas-gerais` | `/noticias-por-tag` | `/noticias-por-prioridade`

**Feedback (3)**: POST `/api/feedback` | GET `/api/feedback` | POST `/api/feedback/{id}/process`

**Research (6)**: POST/GET para `/api/research/deep/start`, `/{job_id}`, `/cluster/{id}` | idem para `/social/`

**Cluster Update (2)**: PUT `/api/cluster/{id}/update` | GET `/api/cluster/{id}/alteracoes`

**Infra (3)**: GET `/health` | GET `/api/health` | GET `/` (serve frontend)

### Background Tasks (10)
- `processar_artigo_background(id)` - Processa 1 artigo
- `gerar_resumo_background(cluster_id)` - Gera resumo de 1 cluster
- `carregar_arquivos_background(dir)` - Carrega PDFs/JSONs de diretorio
- `processar_arquivo_upload_com_progresso(path, ext, db, file_id)` - Upload com progresso
- `processar_artigos_via_script()` - Executa process_articles.py completo
- `_executar_deep_research(job_id, cluster_id, query)` - Pesquisa profunda via Gemini
- `_executar_social_research(job_id, cluster_id, query)` - Pesquisa social via Grok

---

## 8a. Autenticacao e Multi-Tenant (v3.0)

### JWT Auth Flow

- **Librarias**: `python-jose` (JWT), `passlib[bcrypt]` (hash de senha)
- **Header**: `Authorization: Bearer <token>` em todas as requisicoes autenticadas
- **Storage**: Frontend guarda `silva_auth` em localStorage (username, email, role, user_id, token, ts)

### Endpoints de Auth

| Endpoint | Metodo | Descricao | Auth |
|---|---|---|---|
| `/api/auth/login` | POST | Login: `{ email, senha }` -> JWT + user | Nao |
| `/api/auth/me` | GET | Retorna usuario atual (validacao de token) | Sim |
| `/api/auth/register` | POST | Registro de novo usuario (admin) | Admin |
| `/api/auth/users` | GET | Lista usuarios (admin) | Admin |
| `/api/auth/users/{id}` | PUT/DELETE | Atualiza/remove usuario (admin) | Admin |

### Dependency Injection (`main.py`)

| Funcao | O que faz | Uso |
|---|---|---|
| `get_current_user(credentials, db)` | Extrai Bearer token, valida JWT, retorna user ou None | Opcional — endpoints que aceitam user anonimo |
| `require_auth(credentials, db)` | Idem, mas exige token valido — 401 se ausente/invalido | Obligatorio — endpoints protegidos |
| `require_admin(credentials, db)` | Chama `require_auth` e valida `role == admin` — 403 se nao admin | Endpoints administrativos |

### Per-User Preferences e Resumos

- `GET /api/preferencias` / `PUT /api/preferencias` — CRUD preferencias do usuario logado
- `GET /api/templates-resumo` / POST/PUT/DELETE — Templates de resumo (criados por usuario, compartilhaveis)
- `POST /api/resumo-diario/gerar` — Gera resumo personalizado (usa preferencias + template)
- `GET /api/resumo-diario/meu` — Retorna resumo do dia do usuario

---

## 9. Frontend (`script.js` ~120 funcoes, `settings.js` ~80 funcoes)

### Feed (script.js) - Fluxo Principal

```
DOMContentLoaded -> setupEventListeners() -> carregarContadoresSimples() -> carregarFeed()
  |
  carregarFeed() -> verifica cache -> carregarClustersPorPrioridade()
    |
    P1 (todas paginas) -> renderiza -> P2 (todas paginas) -> renderiza -> P3 (todas paginas) -> renderiza
    |
    carregarTagsDisponiveis() -> atualizarFiltrosCategoria()
```

### Funcoes Criticas do Frontend

| Funcao | O que faz | Endpoints |
|---|---|---|
| `carregarFeed()` | Carrega feed (cancela ativos, verifica cache, carrega progressivo) | /api/feed |
| `carregarClustersPorPrioridade(date, token)` | Carrega P1, P2, P3 em sequencia | /api/feed?priority= |
| `renderizarClusters()` | Renderiza cards (P1/P2 expandidos, P3 agrupados por tag) | - |
| `filterAndRender()` | Aplica filtros de prioridade e categoria | - |
| `openModal(clusterId)` | Abre deep-dive, carrega detalhes | /api/cluster/{id} |
| `expandirResumo(clusterId)` | Expande resumo com IA (cache + retry backoff) | POST /api/clusters/{id}/expandir-resumo |
| `salvarAlteracoes()` | Salva edicoes de cluster | PUT /api/cluster/{id}/update |
| `enviarMensagemChat()` | Envia mensagem ao chat do cluster | POST /api/chat/send |
| `registrarFeedbackCluster(id, tipo)` | Like/dislike | POST /api/feedback |
| `carregarSourcersDisponiveis()` | Lista fontes para date/type | GET /api/sourcers |
| `sendMessage(msg)` | Envia mensagem ao Estagiario | POST /api/estagiario/send |

### Cache
- **Cluster cache**: `clusters_{date}` | TTL: 5min hoje, 7 dias historico
- **Expansion cache**: `expand_{clusterId}` | Sem expiracao (sessao)
- **Invalidacao**: Troca de aba, troca de data, manual

### v3.0: Onboarding, Hero e Docs

**Onboarding flow**: `verificarOnboarding()` em `script.js` detecta preferencias vazias via `GET /api/preferencias`. Se o usuario nao tem preferencias configuradas, exibe modal para selecionar tags de interesse. Usado para personalizar resumo diario.

**Hero section**: Secao `#daily-summary-hero` no topo de `index.html` exibe o resumo do dia do usuario. Inicialmente oculta (`display:none`); exibida via `carregarResumoDiario()` quando ha resumo disponivel. Botoes: "Gerar / Atualizar Resumo", timestamp, alerta de novos eventos.

**Docs page**: `frontend/docs.html` — renderizador de documentacao com **marked.js** (Markdown) e **mermaid.js** (diagramas). Sidebar com indice de documentos, conteudo principal em HTML gerado a partir de Markdown. Link de volta para feed.

### Settings (settings.js) - 5 Abas
1. **Artigos**: Tabela paginada + filtros + sort client-side + CRUD
2. **Clusters**: Idem
3. **Prompts**: Sub-abas (Tags CRUD, Prioridades CRUD, Templates CRUD)
4. **BI**: Chart.js (tags pie, prioridade pie, series temporal, rankings)
5. **Feedback**: Lista com marcacao de processado

---

## 10. Agente Estagiario v2 (`agents/estagiario/`)

### Fluxo Principal (ReAct — `executor.py`)
```
POST /api/estagiario/send
  -> EstagiarioAgent.answer_with_context(question, chat_history, date_str)
     -> answer(question, date_str, history_lines)
        -> EstagiarioExecutor.run(user_input, chat_history, data_referencia)
           |
           Loop ReAct (max 10 iteracoes):
             1. Monta prompt com REACT_PROMPT_TEMPLATE + scratchpad
             2. LLM gera Thought + Action (JSON)
             3. Parse JSON (com retry de parsing, max 2 tentativas)
             4. Se "Final Answer" -> retorna resposta Markdown
             5. Se tool -> executa via ToolExecutor -> append observation ao scratchpad
             6. Se parsing falhou -> append erro -> tenta novamente
```

### Protocolo de Execucao (Prompt)
1. **PLANEJE**: Na primeira iteracao, listar tools a usar. Comecar SEMPRE por `list_cluster_titles`.
2. **APROFUNDE**: Usar `get_cluster_details` nos clusters relevantes.
3. **BUSCA SEMANTICA**: Para perguntas abertas, usar `semantic_search`.
4. **RESPONDA**: "Final Answer" com Markdown formatado, sem mencionar tools/clusters/IDs.

### Ferramentas (`tools/definitions.py`)

| Ferramenta | Input | O que faz |
|---|---|---|
| `list_cluster_titles` | data? | Lista TODOS os clusters (id, titulo, tags, prioridade, fontes) — leve, para planejamento |
| `query_clusters` | data, prioridade, palavras_chave, limite | Busca clusters com filtros |
| `get_cluster_details` | cluster_id | Detalhes completos (artigos, resumo, fontes) |
| `update_cluster_priority` | cluster_id, nova_prioridade | Altera prioridade (unitario) |
| `semantic_search` | consulta, limite | Busca semantica por embeddings |

### UI: Input Inline + Side Panel
- Card compacto com 1 linha: input placeholder + botao "Enviar"
- Ao enviar ou clicar no card: abre side-panel (400px) a direita com chat completo
- Side-panel: header navy, thread de mensagens, input na base

---

## 10a. Agente de Resumo Diario (v4.0) (`agents/resumo_diario/`)

### Arquitetura: Chassis + Slots (PROMPT_MASTER_V2)

| Camada | Responsabilidade | Editavel pelo usuario? |
|---|---|---|
| **Chassis (imutavel)** | Rejeicao de ruido (`_REJEICAO_MACRO_PERSONAS`), tools, formato JSON, secoes obrigatorias, regra de volume | Nunca |
| **Slots (personalizaveis)** | Tags foco, empresas no radar, teses juridicas, instrucao livre, tamanho | Sim, via modal de preferencias |

### Dois Modos de Operacao

| Modo | Prompt | Chamadas LLM |
|---|---|---|
| **Unificado (terminal/batch)** | `PROMPT_RESUMO_UNIFICADO_V1` — 3 secoes fixas (distressed, regulatorio, estrategico) | 1 por execucao |
| **Per-user (v4.0 API)** | `PROMPT_MASTER_V2` — chassis imutavel + slots personalizaveis | 1 por usuario |

### Secoes tematicas (PROMPT_MASTER_V2)

| Secao | Emoji | Condicao |
|---|---|---|
| `foco_analista` | 🎯 | So injetada se usuario configurou empresas/teses/tags |
| `distressed` | 💀 | Sempre |
| `estrategico` | 🏛️ | Sempre |
| `regulatorio` | ⚖️ | Sempre |
| `internacional` | 🌍 | Sempre (avalia clusters com tipo_fonte=="internacional") |

**Nao existe secao "geral".** Eventos fora das 5 secoes sao ruido. Pydantic `Literal` estrito barra secoes inventadas pelo LLM.

### Contexto Compartilhado

- `_build_context_block()`: Recolhe TODOS os clusters do dia UMA VEZ.
- Cache: invalidado por `max(updated_at)` dos clusters do dia.
- O contexto e **compartilhado** entre todos os usuarios — nunca duplicado. Economia de tokens.

### Tools (`tools/definitions.py`)

| Tool | Input | O que faz | Requer |
|---|---|---|---|
| `obter_textos_brutos_cluster` | cluster_id | Retorna amostra (ate 3000 chars) dos textos originais do cluster | - |
| `buscar_na_web` | query | Busca na web via Tivaly API | `TIVALY_API_KEY` |

**Contratos Pydantic**: `ClusterSelecionado` (secao: `Literal` estrito), `ResumoDiarioContract` — validacao do JSON de saida do LLM.

### Fluxo Per-User (v4.0)

1. Le preferencias do usuario (`get_preferencias_usuario`)
2. Extrai slots: `tags_interesse`, `empresas_radar`, `teses_juridicas`, `instrucoes_resumo` de `config_extra`
3. `_build_user_prompt()` injeta slots no chassis `PROMPT_MASTER_V2` (condicional: oculta secao foco_analista se slots vazios)
4. Usa contexto compartilhado (`_build_context_block`)
5. Uma chamada LLM por usuario
6. Pre-sanitiza secoes invalidas → Pydantic valida → persiste em `resumos_usuario`

### Modelo de Custo (v4.1 — Resumo Default)

- **Contexto**: lido UMA vez, reutilizado para todos os usuarios.
- **Resumo Default**: 1 chamada LLM unificada, salvo com `user_id=NULL`. Todos os usuarios sem prefs customizadas veem o default.
- **Per-User**: APENAS para quem tem `empresas_radar`, `teses_juridicas`, `instrucoes_resumo` ou `tags_interesse` preenchidos.
- **100 usuarios (todos default)** = 1 chamada LLM total (antes eram 100).
- `user_has_custom_prefs()` em `backend/crud.py` determina quem precisa de resumo personalizado.
- READ-ONLY: nao altera clusters, prioridades ou tags.

---

## 11. Busca Semantica (`semantic_search/`)

- `embedder.py`: OpenAI text-embedding-3-small (fallback hash deterministico)
- `store.py`: CRUD em `semantic_embeddings` (upsert_embedding_for_artigo, fetch_all_embeddings)
- `search.py`: Similaridade cosseno em memoria (carregar todos + np.dot)
- v2.0: Coluna `embedding_v2` (BYTEA 768d Gemini) em artigos_brutos. Integrada ao historian_node via `get_similar_articles_by_embedding()` (cosine em Python). Se pgvector instalado: tipo `vector(768)` + HNSW index para busca nativa.

---

## 12. Deploy: Fluxo Local -> Producao (`run_complete_workflow.py` + `migrate_incremental.py`)

### Workflow Diario do Usuario

O usuario cola PDFs na pasta `../pdfs/` e executa `run_complete_workflow.py`. **Nao ha streaming** - e processamento em lote (batch).

```
run_complete_workflow.py
  |
  ETAPA 0: check_and_start_local_db()
  |         Conecta localhost:5433/devdb. Se offline, tenta start_db.cmd.
  |
  PRE-STEP: run_feedback_learning()
  |          scripts/analyze_feedback.py --days 90 --min-samples 3 --save
  |          Analisa likes/dislikes -> gera REGRAS_APRENDIDAS -> salva em prompt_configs
  |          Regras ficam disponiveis via get_feedback_rules() para Etapas 3 e 4
  |
  ETAPA 1: run_load_news()
  |         Subprocess: python load_news.py --dir ../pdfs --direct --yes
  |         Carrega PDFs/JSONs da pasta para artigos_brutos (status=pendente)
  |
  ETAPA 2: run_process_articles()
  |         Subprocess: python process_articles.py
  |         Pipeline v1+v2 integrado (4 etapas com Graph-RAG)
  |
  ETAPA 3: run_migrate_incremental()
  |         Subprocess: python -m migrate_incremental --source local --dest heroku --include-all
  |         Sincroniza TODAS as 21+ tabelas para producao
  |
  ETAPA 4: run_notify()
  |         scripts/notify_telegram.py --limit 50
  |         Notificacoes individuais de clusters novos (se TELEGRAM configurado)
  |
  ETAPA 5: run_telegram_briefing()
            send_telegram.py (TelegramBroadcaster)
            Daily Briefing sintetizado P1/P2 + contexto grafo v2 (se TELEGRAM configurado)
            Idempotente: nao reenvia se ja enviou hoje
```

### migrate_incremental.py - Sincronizacao Local -> Heroku

**Ordem de execucao** (respeita FKs):
1. `migrate_clusters()` -> Retorna `cluster_id_map` (ID local -> ID heroku)
2. `migrate_artigos()` -> Usa `cluster_id_map` para FK
3. `migrate_sinteses()`
4. `migrate_configuracoes()`
5. `migrate_cluster_alteracoes()` -> Usa `cluster_id_map`
6. `migrate_chat()` -> Usa `cluster_id_map` (sessoes + mensagens)
7. `migrate_prompts()` -> Tags, prioridades, templates
8. `migrate_graph_entities()` -> Retorna `entity_uuid_map` (DEVE rodar ANTES de edges)
9. `migrate_graph_edges()` -> Usa `entity_uuid_map` + busca artigo por hash
10. `migrate_feedback()` -> Busca artigo por hash no destino
11. `migrate_estagiario_chat()` -> Sessoes + mensagens
12. `migrate_research_jobs()` -> Deep + Social, usa `cluster_id_map`

**Flags CLI**:
- `--include-all` (usado pelo run_complete_workflow.py): Sincroniza tudo
- `--include-graph`: Apenas grafo v2
- `--include-feedback`: Apenas likes/dislikes
- `--include-prompts`: Apenas prompts configuraveis
- `--include-chat`: Apenas chat de clusters
- `--include-estagiario`: Apenas chat do agente
- `--include-research`: Apenas research jobs
- `--only clusters,artigos`: Filtra entidades especificas
- `--since 2026-02-08T00:00:00`: Forca timestamp de inicio

**Metadados**: `last_migration.txt` armazena timestamp ISO UTC da ultima sync.

### REGRA CRITICA

**Toda nova tabela em `database.py` DEVE ser adicionada ao `migrate_incremental.py`**, caso contrario os dados ficam presos no localhost e producao nao recebe a inteligencia gerada.

### Variaveis de Ambiente

| Variavel | Obrigatoria | Descricao |
|---|---|---|
| `DATABASE_URL` | Sim | Conexao PostgreSQL local |
| `GEMINI_API_KEY` | Sim | API Google Gemini (embeddings + LLM) |
| `OPENAI_API_KEY` | Nao | Embeddings semanticos alternativos |
| `TELEGRAM_BOT_TOKEN` | Nao | Token do @BotFather para notificacoes/briefing |
| `TELEGRAM_CHAT_ID` | Nao | ID do canal/grupo Telegram destino |
| `V2_SHADOW_MODE` | Nao | `1` para modo sombra v2 (debug) |
| `FEEDBACK_RULES_ENABLED` | Nao | `0` para desligar injecao de feedback rules |
| `ESTAGIARIO_REACT` | Nao | `1` para modo ReAct do agente |
| `TIVALY_API_KEY` | Nao | API Tivaly para tool buscar_na_web do agente de resumo diario |

Checklist:
1. Import nos dois blocos (try/except) no topo do arquivo
2. Funcao `migrate_<entidade>()` (idempotente, incremental, respeita FKs)
3. Flag `--include-<entidade>` no argparse
4. Chamada na funcao `main()` com condicional
5. SQL de migracao em `scripts/` para criar tabela no Heroku

---

## 12a. Pipeline Micro-Batch (v3.0) (`run_complete_workflow.py`)

### run_microbatch_cycle()

- **Funcao**: `run_microbatch_cycle(pdfs_dir=None, batch_interval_minutes=3)`
- **Objetivo**: Processa PDFs em micro-lotes; acumula por N minutos, processa o lote inteiro de uma vez. Evita overhead de subprocess por PDF.
- **Uso**: `python run_complete_workflow.py --microbatch --batch-interval 3`

### Lock File (`.microbatch.lock`)

- **Caminho**: `{pdfs_dir}/.microbatch.lock`
- **Conteudo**: `{pid}|{timestamp}` — identifica processo ativo
- **Protecao**: Evita race conditions — se outro ciclo ainda esta rodando, o novo ciclo aborta e espera o proximo intervalo.
- **Stale detection**: Se PID do lock nao existe (psutil), ou lock tem mais de 10 min, remove e prossegue.

### PDFs para _processed/

Apos processamento bem-sucedido (`run_load_news` + `run_process_articles`), cada PDF em `{pdfs_dir}/*.pdf` e **movido** para `{pdfs_dir}/_processed/`. Evita reprocessamento no proximo ciclo.

### Ordem do Ciclo

1. Adquire lock
2. Lista `*.pdf` pendentes
3. `run_load_news()` — carrega para artigos_brutos
4. `run_process_articles()` — pipeline completo
5. Move PDFs para `_processed/`
6. `run_migrate_incremental()` — sync producao
7. `run_notify()` — notificacoes Telegram
8. Libera lock

---

## 13. Feedback Learning System

### Arquitetura

O sistema de Feedback Learning usa o ciclo **Coleta → Analise → Regras → Injecao** para refinar CONSERVADORAMENTE os prompts de classificacao/resumo com base nos likes/dislikes dos analistas.

```
Frontend (Like/Dislike)
  → POST /api/feedback → feedback_noticias (com metadados: tag, prioridade, entidades)
  
scripts/analyze_feedback.py --save
  → Coleta feedback dos ultimos 90 dias
  → Descobre padroes (tags rejeitadas, prioridades inflacionadas, entidades irrelevantes)
  → Gera REGRAS_APRENDIDAS (texto humano-legivel)
  → Salva em prompt_configs (chave: FEEDBACK_RULES)
  
Pipeline (Etapas 3 e 4)
  → get_feedback_rules() (cache 10min)
  → Injeta como ADDENDUM no final do prompt (nao altera o prompt original)
  → LLM le as regras e ajusta classificacao/resumo sutilmente
```

### Principios de Seguranca

1. **Aditivo, nunca destrutivo**: Regras sao injetadas como ADDENDUM no final do prompt, nunca substituem texto existente
2. **Kill switch**: `FEEDBACK_RULES_ENABLED=0` desliga instantaneamente
3. **Minimo de amostras**: Padrao so e considerado com >= 3 feedbacks (evita overfitting)
4. **Regras fixas**: `analyze_feedback.py` inclui domain knowledge fixo (deals <R$10M = P3, esportes = IRRELEVANTE)
5. **Cache**: Regras recarregadas a cada 10 minutos (nao a cada chamada LLM)

### Componentes

| Arquivo | Papel |
|---|---|
| `frontend/script.js` | Botoes Like/Dislike → POST /api/feedback |
| `backend/main.py` | Endpoint POST /api/feedback (salva com metadados ricos) |
| `backend/database.py` | `FeedbackNoticia` + `PromptConfig` (ORM) |
| `backend/crud.py` | `create_feedback`, `list_feedback`, `mark_feedback_processed` |
| `scripts/analyze_feedback.py` | Analise de padroes → gera regras → salva em `prompt_configs` |
| `backend/prompts.py` | `get_feedback_rules()` — carrega regras com cache 10min |
| `process_articles.py` | Injecao em Etapa 3 (sintese) e Etapa 4 (consolidacao) |
| `run_complete_workflow.py` | `run_feedback_learning()` — roda analise antes do processamento |

---

## 14. Modulo de Disseminacao Telegram

### Componentes

| Componente | Arquivo | Papel |
|---|---|---|
| Notificacoes Individuais | `scripts/notify_telegram.py` | Envia 1 mensagem por cluster novo (Etapa 4) |
| Daily Briefing | `backend/broadcaster.py` | Gera Morning Call sintetizado P1/P2 via LLM (Etapa 5) |
| CLI Briefing | `send_telegram.py` | Wrapper para teste/uso manual |
| Prompt | `backend/prompts.py` | `PROMPT_TELEGRAM_BRIEFING_V1` (HTML, emojis, contexto v2) |

### Fluxo do Daily Briefing (`TelegramBroadcaster`)

```
1. Query: clusters P1/P2 do dia (ativos, nao IRRELEVANTE)
2. Enriquecimento v2: get_context_for_cluster() → contexto_historico (grafo + vetorial)
3. LLM: Gemini Flash + PROMPT_TELEGRAM_BRIEFING_V1 → HTML formatado
4. Split: Quebra em partes de ≤4000 chars (respeita paragrafos)
5. Envio: POST https://api.telegram.org/bot<TOKEN>/sendMessage (parse_mode=HTML)
6. Idempotencia: Verifica logs_processamento do dia antes de enviar
7. Auditoria: Registra em logs_processamento (componente: broadcaster)
```

### Edge Cases

- **0 clusters P1/P2** ("Dia de Tedio"): Aborta sem chamar LLM, registra log
- **Telegram nao configurado**: Aborta silenciosamente com mensagem orientativa
- **Mensagem > 4096 chars**: Split automatico com numeracao de partes
- **Falha de envio**: Registra log de erro, nao bloqueia pipeline

### Configuracao

```
# backend/.env (LOCAL — nao so no Heroku)
TELEGRAM_BOT_TOKEN=token_do_botfather
TELEGRAM_CHAT_ID=-100XXXXXXXXXX
```

Spec completa: `docs/TELEGRAM_MODULE_SPEC.md`

### 14.1. Listener Telegram (Coleta de PDFs)

Subprojeto independente em `TELEGRAM_LISTENER/` — escuta grupos/canais usando a conta do usuário (Telethon, não bot), baixa PDFs de jornais e dispara o `load_news.py` do pipeline principal.

| Componente | Arquivo | Papel |
|---|---|---|
| Agente | `TELEGRAM_LISTENER/agent.py` | Conexão Telethon, detecção de docs, download, dedup |
| Config | `TELEGRAM_LISTENER/config.py` | Padrões de jornais, caminhos |
| CLI | `TELEGRAM_LISTENER/run.py` | Ponto de entrada: `python -m TELEGRAM_LISTENER` |

Variáveis: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`, `TELEGRAM_LISTEN_CHATS`. Ver `TELEGRAM_LISTENER/README.md`.
