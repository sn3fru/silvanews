# Roadmap Futuro — Estagiário (Fases 2, 2.5 e 3)

Este documento descreve as próximas fases para evoluir o agente para uma arquitetura autônoma com RAG e streaming, sem quebrar o backend existente.

## Fase 2 — RAG (Busca Semântica com pgvector)

- Objetivo: Habilitar buscas por similaridade nos `clusters_eventos` e (opcional) `artigos_brutos`.
- Não alterar endpoints existentes; adicionar apenas novas rotas ou usar ferramentas internas do agente.

### Passos
1) Ativar extensão e migrar tipos/índices (em ambiente controlado):
```
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE clusters_eventos
ALTER COLUMN embedding_medio TYPE vector(768)
USING embedding_medio::vector;
ALTER TABLE artigos_brutos
ALTER COLUMN embedding TYPE vector(768)
USING embedding::vector;
CREATE INDEX ON clusters_eventos USING ivfflat (embedding_medio vector_cosine_ops) WITH (lists = 100);
```
2) Garantir que o pipeline continue preenchendo os embeddings no mesmo shape (768 por exemplo).
3) Criar uma tool `semantic_search_clusters(data, texto_busca, limite)` que:
   - Gera embedding do texto via mesmo modelo do pipeline
   - Executa a query `ORDER BY embedding_medio <-> :embedding_query` (cosine)
   - Retorna `{id, titulo, resumo, prioridade, tag}`
4) No `EstagiarioExecutor`, permitir que o LLM opte por `semantic_search_clusters` quando a pergunta for aberta/ambígua.

## Fase 2.5 — Motor do Agente (Foundation)

- Objetivo: Substituir a lógica interna de `EstagiarioAgent.answer()` pelo `EstagiarioExecutor` com ciclo ReAct (sem streaming ainda), mantendo o endpoint atual `/api/estagiario/send` intacto.

### Passos Técnicos
1) Toolbelt formal (Pydantic + contratos):
   - Consolidar `agents/estagiario/tools/definitions.py` com ferramentas unitárias e seguras:
     - `query_clusters(data?, prioridade?, palavras_chave?, limite?)`
     - `get_cluster_details(cluster_id)`
     - `update_cluster_priority(cluster_id, nova_prioridade)`
   - Adicionar a tool de RAG da Fase 2: `semantic_search_clusters(data?, texto_busca, limite?)` (quando disponível no DB).
2) Executor ReAct:
   - `agents/estagiario/executor.py` com laço curto (até 4 iterações): formata `REACT_PROMPT_TEMPLATE`, chama LLM, faz parse do bloco JSON da ação, executa tool, acumula `agent_scratchpad` e decide pela ação especial `Final Answer`.
   - Prompt em `agents/estagiario/prompts.py` descrevendo ferramentas, formato JSON e regras de saída (Markdown, sem descrever passos).
3) Integração no agente:
   - Em `agents/estagiario/agent.py`, permitir ativação via `ESTAGIARIO_REACT=1` (já suportado). Em caso de erro, cair no pipeline determinístico atual como fallback.
4) Testes e contratos:
   - Golden-set de perguntas fixas (smoke tests) cobrindo: contagem de irrelevantes, busca por prioridade/tag, consulta genérica com síntese curta, atualização unitária de prioridade.
   - Verificar que as ações nunca são em lote e que o output final é Markdown válido.

## Fase 3 — Streaming ReAct na API

- Objetivo: Enviar Thought/Action/Observation em tempo real para o frontend.

### Passos
1) Adicionar endpoint de streaming (sem substituir o atual):
   - Nova rota `GET/POST /api/estagiario/stream` retornando `StreamingResponse` com eventos NDJSON.
2) Tornar `EstagiarioExecutor.run(...)` um gerador que `yield` cada passo:
   - `{ "type": "thought", "content": "..." }`
   - `{ "type": "action", "tool": "...", "input": { ... } }`
   - `{ "type": "observation", "content": { ... } }`
   - `{ "type": "final_answer", "content": "markdown..." }`
3) Frontend: adaptar o modal para consumir streaming e atualizar a UI em tempo real.

### Observações
- Manter compatibilidade com o endpoint existente `/api/estagiario/send`.
- Streaming pode ser opcional por query param `?stream=1`.

## Notas de compatibilidade e UX
- O modo ReAct é opt-in via variável de ambiente; não quebra integrações existentes.
- A UI pode exibir um modal de progresso com etapas (“Entendendo → Planejando → Consultando DB → Sintetizando”), reaproveitando os eventos do executor quando o streaming for habilitado.
