# v2.0 - Arquitetura Graph-RAG Integrada

## Status: INTEGRADO NO PIPELINE PRINCIPAL

A v2.0 foi implementada seguindo a estrategia **Strangler Fig** e agora esta **totalmente integrada** nas 4 etapas do pipeline principal. Nao roda mais como modo sombra separado — o Graph-RAG e o motor principal.

---

## Resumo Executivo

O pipeline evoluiu de um ETL monolitico linear para uma **Arquitetura Hibrida (Graph-RAG)** onde cada etapa utiliza embeddings semanticos (768d Gemini) e um grafo de conhecimento (entidades + arestas) para tomar decisoes mais inteligentes.

---

## Arquivos Criados/Alterados

### Novos (v2.0)

| Arquivo                             | Descricao                                                                             |
| ----------------------------------- | ------------------------------------------------------------------------------------- |
| `backend/agents/__init__.py`      | Package dos agentes                                                                   |
| `backend/agents/nodes.py`         | Nos do LangGraph: gatekeeper, entity_extraction, entity_resolution, historian, writer |
| `backend/agents/graph_crud.py`    | CRUD do grafo de conhecimento (entidades, arestas, queries, contexto)                 |
| `backend/workflow.py`             | Workflow LangGraph (StateGraph) - disponivel para debug/comparacao                    |
| `scripts/migrate_graph_tables.py` | Migracao SQL para tabelas do grafo (local)                                            |
| `scripts/apply_graph_heroku.py`   | Migracao SQL para tabelas do grafo (Heroku producao)                                  |
| `scripts/backfill_graph.py`       | Backfill de entidades e embeddings historicos                                         |
| `scripts/notify_telegram.py`      | Notificacoes Telegram de clusters novos                                               |

### Alterados

| Arquivo                      | Alteracao                                                                                                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/database.py`      | Modelos `GraphEntity`, `GraphEdge`, colunas `embedding_v2`, `ja_notificado`, `notificado_em`                                                    |
| `backend/processing.py`    | `gerar_embedding_v2()` (Gemini 768d), `cosine_similarity_bytes()`, `verificar_duplicata_semantica()`                                                |
| `process_articles.py`      | **v2 integrado**: `enriquecer_artigo_v2()` na Etapa 1, dicas similaridade na Etapa 2, contexto grafo na Etapa 3, similaridade clusters na Etapa 4 |
| `run_complete_workflow.py` | Orquestra: ingestao → processamento v2 → migracao → notificacao. Suporta `--scheduler`                                                               |
| `migrate_incremental.py`   | Migra entidades, arestas, embeddings, feedback, notificacoes para Heroku                                                                                  |

---

## Como o v2 Funciona em Cada Etapa

### ETAPA 1: Processamento + Enriquecimento Graph-RAG

```
processar_artigo_sem_cluster() + enriquecer_artigo_v2()
```

1. Processa artigo normalmente (metadata, validacao, embedding hash 384d)
2. **v2**: Gera `embedding_v2` (768d Gemini) via `gerar_embedding_v2()`
3. **v2**: Extrai entidades via LLM (Gemini Flash) usando `PROMPT_ENTITY_EXTRACTION`
4. **v2**: Resolve nomes canonicos e persiste no grafo via `link_artigo_to_entities()`
5. Marca como `pronto_agrupar`

### ETAPA 2: Agrupamento + Dicas de Similaridade

```
processar_lote_incremental() / agrupar_noticias_com_prompt()
```

1. Monta prompt com titulos dos artigos e clusters existentes
2. **v2**: Calcula similaridade cosseno (pairwise) entre artigos do lote via `embedding_v2`
3. **v2**: Calcula similaridade artigos x clusters existentes
4. **v2**: Injeta DICAS DE SIMILARIDADE no prompt (ex: "Noticias 3 e 7: 92% similaridade")
5. LLM decide agrupamento com informacao semantica adicional

### ETAPA 3: Classificacao/Resumo + Contexto Historico

```
classificar_e_resumir_cluster()
```

1. Monta prompt com textos completos dos artigos do cluster
2. **v2**: Chama `get_context_for_cluster()` que busca:
   - Contexto temporal do grafo: clusters dos ultimos 7 dias com as mesmas entidades
   - Contexto vetorial: artigos semanticamente similares dos ultimos 30 dias
3. **v2**: Injeta CONTEXTO HISTORICO no prompt
4. LLM pode gerar resumos como "Este e o terceiro anuncio do tipo nesta semana..."

### ETAPA 4: Consolidacao + Similaridade entre Clusters

```
consolidacao_final_clusters()
```

1. Monta prompt com titulos, tags e prioridades dos clusters do dia
2. **v2**: Calcula embedding medio por cluster (media dos `embedding_v2` dos artigos)
3. **v2**: Identifica pares de clusters com alta similaridade (>=75%)
4. **v2**: Injeta DICAS DE MERGE no prompt
5. LLM sugere merges com informacao semantica adicional

---

## Tabela de Integracao

| Etapa             | Embeddings v2 |    Grafo    |  Similaridade  | Funcao v2                     |
| ----------------- | :-----------: | :----------: | :------------: | ----------------------------- |
| **Etapa 1** | Gera e salva | NER + edges |       -       | `enriquecer_artigo_v2()`    |
| **Etapa 2** |   Consulta   |      -      | Entre artigos | `cosine_similarity_bytes()` |
| **Etapa 3** | Via contexto | Historico 7d |  Artigos 30d  | `get_context_for_cluster()` |
| **Etapa 4** | Media cluster |      -      | Entre clusters | `cosine_similarity_bytes()` |

---

## Como Usar

### Pipeline Completo (Recomendado)

```bash
conda activate pymc2
cd btg_alphafeed
python run_complete_workflow.py
```

### Pipeline em Loop (Operacao Continua)

```bash
python run_complete_workflow.py --scheduler --interval 60
```

### Backfill do Grafo (Uma Vez, Apos Setup)

```bash
python scripts/backfill_graph.py --days 30 --batch 50
```

### Debug: Modo Sombra (Comparacao v1 vs v2)

```bash
V2_SHADOW_MODE=1 python process_articles.py
```

---

## Degradacao Graciosa

Se o Gemini estiver indisponivel:

- **Etapa 1**: Artigo processado normalmente sem embedding_v2/NER/grafo
- **Etapa 2**: Agrupamento funciona sem dicas de similaridade (apenas LLM textual)
- **Etapa 3**: Resumo gerado sem contexto historico (apenas textos do cluster)
- **Etapa 4**: Consolidacao funciona sem similaridade de embeddings (apenas LLM textual)

Nenhuma etapa falha. O pipeline retorna ao comportamento v1 automaticamente.

---

## Regras de Ouro

1. **NUNCA diluir** o Gatekeeper V13 - encapsular, nao reescrever
2. **NUNCA misturar** NACIONAL/INTERNACIONAL em clusters
3. **Preservar** `texto_bruto` imutavel
4. **v2 nunca bloqueia**: Falhas de embedding/NER/grafo sao silenciosas
5. **Prompts intocados**: v2 injeta informacao ADICIONAL, nao altera prompts existentes

---

## Dependencias

| Pacote                  | Uso                                  | Obrigatorio             |
| ----------------------- | ------------------------------------ | ----------------------- |
| `langgraph`           | Orquestracao de agentes (modo debug) | Nao (fallback linear)   |
| `google-generativeai` | Embeddings + NER (Gemini Flash)      | Sim (para v2 funcionar) |

---

## Proximos Passos

1. **pgvector nativo**: Instalar extensao pgvector no PostgreSQL para HNSW index nativo
2. ~~**DSPy**: Otimizacao automatica de prompts baseada em feedback~~ → **Implementado como Feedback Learning System** (conservador, sem DSPy puro):
   - `scripts/analyze_feedback.py` analisa likes/dislikes (tags, prioridades, entidades, keywords)
   - Gera REGRAS_APRENDIDAS e salva em `prompt_configs` (tabela)
   - `get_feedback_rules()` injeta como ADDENDUM nos prompts de Etapa 3 e 4
   - Kill switch: `FEEDBACK_RULES_ENABLED=0`
   - Integrado no pipeline via `run_feedback_learning()` (pre-step automatico)
3. **Multi-LLM**: Gemini Flash para extracao + Versoes PRO para resumos P1
4. **Re-resumo de cluster**: Quando artigo e anexado, re-gerar resumo com contexto historico
5. ~~**Interesses por usuario + notificacao Telegram**~~ → **Parcialmente implementado**:
   - `scripts/notify_telegram.py`: Notificacoes individuais de clusters novos (Etapa 4)
   - `backend/broadcaster.py` + `send_telegram.py`: Daily Briefing sintetizado P1/P2 com contexto v2 (Etapa 5)
   - Pendente: filtragem personalizada por usuario, WhatsApp
