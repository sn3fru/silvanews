# BTG AlphaFeed - Guia de Operacoes

---

## 1. Setup

### Pre-requisitos
- Anaconda (env `pymc2`), PostgreSQL porta 5433
- `backend/.env` com `DATABASE_URL` e `GEMINI_API_KEY`

### Instalacao Completa

```bash
conda activate pymc2
cd btg_alphafeed
pip install -r requirements.txt

# Criar tabelas ORM
python -c "from backend.database import create_tables; create_tables()"

# v2.0: Tabelas do grafo + extensoes (pgvector, pg_trgm)
python scripts/migrate_graph_tables.py

# v2.0: Popular grafo com dados historicos (uma vez)
python scripts/backfill_graph.py --days 90 --limit 5000

# Seed de prompts (opcional)
python tests/seed_prompts.py

# Iniciar servidor
python start_dev.py
```

**URLs**: Frontend `http://localhost:8000/frontend` | API Docs `http://localhost:8000/docs` | Health `http://localhost:8000/health`

---

## 2. Pipeline Diario

### Fluxo Completo (Recomendado)

O usuario cola os PDFs dos jornais na pasta `../pdfs/` e executa:

```bash
conda activate pymc2
python run_complete_workflow.py
```

Esse script automatiza TUDO em sequencia:
1. **ETAPA 0**: Verifica/inicia PostgreSQL local (localhost:5433)
2. **PRE-STEP**: `analyze_feedback.py` — Feedback Learning (analisa likes/dislikes → regras)
3. **ETAPA 1**: `load_news.py --dir ../pdfs --direct --yes` (ingestao de PDFs/JSONs)
4. **ETAPA 2**: `process_articles.py` (pipeline v1+v2 integrado com Graph-RAG)
5. **ETAPA 3**: `migrate_incremental --include-all` (sincroniza LOCAL -> HEROKU)
6. **ETAPA 4**: `notify_telegram.py` (notificacoes individuais, se configurado)
7. **ETAPA 5**: `send_telegram.py` (Daily Briefing sintetizado, se configurado)

### Execucao Manual (Etapas Individuais)

```bash
# Ingestao + Processamento (sem sync para producao)
python load_news.py --dir ../pdfs --direct --yes
python process_articles.py

# Apenas etapa 4 (priorizacao + consolidacao)
python process_articles.py --stage 4

# Modo lote (reprocessamento total)
python process_articles.py --modo lote --stage all

# Reprocessar dia completo
python reprocess_today.py

# Reverter clusters problematicos + reagrupar
python tests/revert_bad_clusters.py
python reprocess_incremental_today.py
```

### Telegram (Notificacoes + Daily Briefing)

```bash
# Apenas teste (mostra briefing sem enviar)
python send_telegram.py --dry-run

# Envia briefing manualmente
python send_telegram.py

# Reenvia mesmo se ja enviou hoje
python send_telegram.py --force

# Briefing de data especifica
python send_telegram.py --day 2026-02-08
```

### Feedback Learning (Refinamento de Prompts)

```bash
# Analisa padroes sem salvar (dry-run)
python scripts/analyze_feedback.py

# Analisa e salva regras no banco
python scripts/analyze_feedback.py --days 90 --min-samples 3 --save

# Desligar injecao de feedback (emergencia)
# No backend/.env:
FEEDBACK_RULES_ENABLED=0
```

### Variaveis de Ambiente

| Variavel | Padrao | Descricao |
|---|---|---|
| `DATABASE_URL` | localhost:5433/devdb | Conexao PostgreSQL |
| `GEMINI_API_KEY` | (obrigatoria) | API do Google Gemini |
| `OPENAI_API_KEY` | (opcional) | Embeddings semanticos |
| `TELEGRAM_BOT_TOKEN` | (opcional) | Token @BotFather para notificacoes |
| `TELEGRAM_CHAT_ID` | (opcional) | ID canal/grupo Telegram destino |
| `FEEDBACK_RULES_ENABLED` | `1` | `0` desliga injecao de feedback rules |
| `V2_SHADOW_MODE` | `0` | Workflow v2 em modo sombra (debug) |
| `ESTAGIARIO_REACT` | `0` | Modo ReAct do agente |

---

## 3. Migracao Local -> Producao

```bash
# TUDO (usado pelo run_complete_workflow.py) - RECOMENDADO
python -m migrate_incremental \
  --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" \
  --dest "postgres://<user>:<pass>@<host>:5432/<db>" \
  --include-all

# Apenas entidades essenciais (mais rapido)
python -m migrate_incremental --source ... --dest ...

# Com grafo v2 + feedback
python -m migrate_incremental --source ... --dest ... --include-graph --include-feedback

# Apenas entidades especificas
python -m migrate_incremental --source ... --dest ... --only clusters,artigos,graph

# Forcar desde uma data especifica
python -m migrate_incremental --source ... --dest ... --include-all --since 2026-02-08T00:00:00
```

### Flags do migrate_incremental.py

| Flag | O que sincroniza |
|---|---|
| (nenhuma flag) | clusters, artigos, sinteses, configs, alteracoes (core) |
| `--include-all` | TUDO (18 tabelas) |
| `--include-graph` | graph_entities + graph_edges (v2 Graph-RAG) |
| `--include-feedback` | feedback_noticias (likes/dislikes) |
| `--include-prompts` | prompt_tags + prompt_prioridade_itens + prompt_templates |
| `--include-chat` | chat_sessions + chat_messages (por cluster) |
| `--include-estagiario` | estagiario_chat_sessions + estagiario_chat_messages |
| `--include-research` | deep_research_jobs + social_research_jobs |
| `--include-logs` | logs_processamento (desabilitado, nao essencial) |
| `--no-update-existing` | Apenas insere novos, nao atualiza existentes |

---

## 4. Referencia Completa de Endpoints (60+)

### Feed

| Metodo | Rota | Params | Funcao | Chama |
|---|---|---|---|---|
| GET | `/api/feed` | data, page, page_size, priority, tipo_fonte, load_full_text | `get_feed()` | `get_metricas_by_date`, `get_clusters_for_feed_by_date` |
| GET | `/api/cluster/{id}` | - | `get_cluster_details()` | `get_cluster_details_by_id` |
| GET | `/api/cluster/{id}/artigos` | - | `get_cluster_artigos()` | `get_artigos_by_cluster` |
| POST | `/api/clusters/{id}/expandir-resumo` | - | `expandir_resumo_cluster()` | `get_textos_brutos_por_cluster`, Gemini LLM |
| GET | `/api/contadores_abas` | data | `get_contadores_abas()` | `get_cluster_counts_by_date_and_tipo_fonte` |
| GET | `/api/sourcers` | data, tipo_fonte | `api_list_sourcers()` | `list_sourcers_by_date_and_tipo` |
| GET | `/api/raw-by-source` | source, data, tipo_fonte | `api_list_raw_by_source()` | `list_raw_articles_by_source_date_tipo` |

### Cluster Updates

| Metodo | Rota | Body | Funcao | Chama |
|---|---|---|---|---|
| PUT | `/api/cluster/{id}/update` | prioridade, tags, motivo | `update_cluster()` | `update_cluster_priority`, `update_cluster_tags` |
| GET | `/api/cluster/{id}/alteracoes` | - | `get_cluster_alteracoes_endpoint()` | `get_cluster_alteracoes` |

### Admin

| Metodo | Rota | Descricao | Background Task |
|---|---|---|---|
| POST | `/admin/processar-pendentes` | Processa artigos pendentes | `processar_artigo_background` por artigo |
| POST | `/api/admin/upload-file` | Upload PDF/JSON | `processar_arquivo_upload_com_progresso` |
| GET | `/api/admin/upload-progress/{id}` | Progresso do upload | Le `upload_progress` dict |
| POST | `/api/admin/process-articles` | Roda process_articles.py | `processar_artigos_via_script` |
| GET | `/api/admin/processing-status` | Status do processamento | Le `processing_state` dict |
| POST | `/admin/gerar-resumo/{id}` | Gera resumo de cluster | `gerar_resumo_background` |
| POST | `/admin/carregar-arquivos` | Carrega dir de PDFs | `carregar_arquivos_background` |
| GET | `/admin/stats` | Stats do banco | `get_database_stats` |
| GET | `/api/admin/alteracoes` | Historico de alteracoes | `get_all_cluster_alteracoes` |

### Settings CRUD

| Metodo | Rota | Params | Descricao |
|---|---|---|---|
| GET | `/api/settings/artigos` | page, limit, id, titulo, jornal, status, tag, prioridade, date, sort_by, sort_dir | Lista artigos |
| GET/PUT/DELETE | `/api/settings/artigos/{id}` | - | CRUD artigo |
| GET | `/api/settings/clusters` | page, limit, id, titulo, tag, prioridade, status, date, sort_by, sort_dir | Lista clusters |
| GET/PUT/DELETE | `/api/settings/clusters/{id}` | - | CRUD cluster |
| GET | `/api/settings/sinteses` | page, limit, date | Lista sinteses |
| GET/PUT/DELETE | `/api/settings/sinteses/{id}` | - | CRUD sintese |
| GET/PUT | `/api/settings/prompts` | - | Get/update prompts compilados (escreve em prompts.py!) |

### Prompts

| Metodo | Rota | Descricao |
|---|---|---|
| GET/POST | `/api/prompts/tags` | Lista/cria tags |
| PUT/DELETE | `/api/prompts/tags/{id}` | Atualiza/deleta tag |
| GET/POST | `/api/prompts/prioridades` | Lista/cria prioridades |
| PUT/DELETE | `/api/prompts/prioridades/{id}` | Atualiza/deleta prioridade |
| GET | `/api/prompts/templates` | Lista templates |
| POST | `/api/prompts/templates` | Upsert template |
| DELETE | `/api/prompts/templates/{id}` | Deleta template |

### Chat

| Metodo | Rota | Body | Chama |
|---|---|---|---|
| POST | `/api/chat/send` | cluster_id, message | `get_or_create_chat_session`, `add_chat_message`, Gemini LLM, `add_chat_message` |
| GET | `/api/chat/{cluster_id}/messages` | - | `get_chat_session_by_cluster`, `get_chat_messages_by_session` |

### Estagiario

| Metodo | Rota | Body | Chama |
|---|---|---|---|
| POST | `/api/estagiario/start` | data (opcional) | `create_estagiario_session` |
| POST | `/api/estagiario/send` | session_id, message | `add_estagiario_message`, `EstagiarioAgent.answer_with_context()`, `add_estagiario_message` |
| GET | `/api/estagiario/messages/{id}` | - | `list_estagiario_messages` |

### BI

| Metodo | Rota | Params | Chama |
|---|---|---|---|
| GET | `/api/bi/series-por-dia` | dias=30 | `agg_noticias_por_dia` |
| GET | `/api/bi/noticias-por-fonte` | limit=20 | `agg_noticias_por_fonte` |
| GET | `/api/bi/noticias-por-autor` | limit=20 | `agg_noticias_por_autor` |
| GET | `/api/bi/estatisticas-gerais` | - | `agg_estatisticas_gerais` |
| GET | `/api/bi/noticias-por-tag` | limit=10 | `agg_noticias_por_tag` |
| GET | `/api/bi/noticias-por-prioridade` | - | `agg_noticias_por_prioridade` |

### Feedback

| Metodo | Rota | Params | Chama |
|---|---|---|---|
| POST | `/api/feedback` | artigo_id, feedback (like/dislike) | `create_feedback` |
| GET | `/api/feedback` | processed, limit | `list_feedback` |
| POST | `/api/feedback/{id}/process` | - | `mark_feedback_processed` |

### Research

| Metodo | Rota | Body | Background Task |
|---|---|---|---|
| POST | `/api/research/deep/start` | cluster_id, query | `_executar_deep_research` (Gemini) |
| GET | `/api/research/deep/{id}` | - | `get_deep_research_job` |
| GET | `/api/research/deep/cluster/{id}` | limit | `list_deep_research_jobs_by_cluster` |
| POST | `/api/research/social/start` | cluster_id, query | `_executar_social_research` (Grok API) |
| GET | `/api/research/social/{id}` | - | `get_social_research_job` |
| GET | `/api/research/social/cluster/{id}` | limit | `list_social_research_jobs_by_cluster` |

### Infra

| Metodo | Rota | Descricao |
|---|---|---|
| GET | `/health` | Health check (testa DB, verifica env vars) |
| GET | `/api/health` | Health check simples |
| GET | `/` | Serve index.html do frontend |
| POST | `/internal/novo-artigo` | Cria artigo (usado por FileLoader) |
| POST | `/internal/processar-artigo` | Processa 1 artigo (background) |

---

## 5. Deploy Heroku

| Arquivo | Conteudo |
|---|---|
| `Procfile` | `web: PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}` |
| `runtime.txt` | `python-3.11.9` |

---

## 6. Troubleshooting

| Problema | Solucao |
|---|---|
| Sem GEMINI_API_KEY | PDFs ingeridos como 1 artigo/pagina (fallback) |
| Conexao DB falhando | Confirmar porta 5433 e DATABASE_URL |
| Sem artigos pendentes | Rodar load_news.py primeiro |
| JSON quebrado do LLM | Lotes menores + 5 estrategias de fallback em extrair_json_da_resposta |
| Clusters duplicados | Rodar Etapa 4 (consolidacao) |
| Tags erradas apos classificacao | _corrigir_tag_deterministica_cluster aplica correcoes hardcoded por keyword |
| v2 modo sombra nao roda | Verificar V2_SHADOW_MODE=1 e pip install langgraph |
| Upload travado | Verificar upload_progress via GET /api/admin/upload-progress/{file_id} |
| Telegram nao envia | Verificar TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no backend/.env LOCAL |
| Briefing reenvia duplicado | Idempotente via logs_processamento. Use --force para forcar reenvio |
| Feedback rules nao aplicam | Rodar `python scripts/analyze_feedback.py --save` manualmente. Verificar FEEDBACK_RULES_ENABLED!=0 |
| prompt_configs nao existe | Rodar `python scripts/migrate_graph_tables.py` para criar a tabela |