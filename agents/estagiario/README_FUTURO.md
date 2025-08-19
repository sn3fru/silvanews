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

## Fase 2.6 — Refatoração de Arquitetura e Robustez do LLM

Objetivo: reduzir acoplamento e duplicações; tornar a manutenção e os testes mais simples.

### 1) Quebrar a "God Class" EstagiarioAgent

- LLMService: encapsular chamadas ao Gemini (config, prompts, retries, rate limiting, parsing de JSON robusto)
- KnowledgeBaseHandler: encapsular acesso ao DB (wrappers `backend.crud` + adaptadores de cache)
- IntentRouter: roteamento de intenção para handlers especializados (EditHandler, QueryHandler, AdminHandler)
- EditHandler: fluxo de update de tag/prioridade/merge
- QueryHandler: consultas e síntese

Impacto: manutenibilidade/testabilidade ↑; cobertura de testes por componente.

### 2) Externalizar Configurações e Constantes

- Criar `agents/estagiario/config.py` (ou .yaml) com:
  - Stop-words, pesos de prioridade, regexes
  - Limites de iteração por hora (e.g., MAX_ITER_PER_HOUR=10)
  - Chaves de features (ex.: ENABLE_BATCH_UPDATES=False)
- Usar Enums para prioridades e operações

### 3) Injeção de Dependência de DB

- Mudar assinatura de `answer` para receber a sessão (`answer(self, db: Session, question: str, ...)`)
- Sessão criada/fechada no nível da API (FastAPI), permitindo DB de teste

### 4) Parsing de JSON do LLM (centralizado)

- Em `LLMService`, criar `parse_json(raw: str) -> dict`:
  - Remove cercas ```json
  - Tenta `json.loads`; se falhar, extrai primeiro objeto `{...}` via regex
  - Logging padronizado; métrica de taxa de malformações

### 5) Prompts Estruturados

- `agents/estagiario/prompts.py` com templates nomeados
- Suporte a versão por chave (A/B) e placeholders explícitos (ex.: {TAGS}, {TITLE}, {SUMMARY})

### 6) Rate Limiting Global

- Implementar contador centralizado (Redis) por janela (ex.: sliding window)
- Respeitar `MAX_ITER_PER_HOUR` global em multi-workers

### 7) Otimizações de Coleta/DB

- `_fetch_clusters`: opção streaming/gerador; limite de páginas; early cutoff quando já houver candidatos suficientes
- Evitar buscas repetidas: manter universo de clusters em memória durante a mesma requisição e filtrar localmente

### 8) Estratégia Determinística Primeiro

- Em comandos estruturados (ex.: `atualize prioridade do cluster 123 para p2`), preferir parsers determinísticos (regex) antes do LLM
- LLM apenas quando a intenção ou o alvo forem ambíguos (abertos/semânticos)

### 9) Logs e Telemetria

- Padronizar logs de entrada/saída do LLM; incluir hashes das entradas
- Métricas: nº de iterações, tempo por etapa, taxa de acerto de pick de candidatos, taxa de malformações de JSON

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

---

## Considerações de Design (Advogado do Diabo)

- O agente está se tornando um "canivete suíço"?
  - Proposta: especializar em subagentes (EditorAgent, ResearchAgent) com um orquestrador simples
- LLM primeiro é ideal?
  - Para comandos estruturados, regex/parsers determinísticos são mais baratos e previsíveis; deixar LLM para casos ambíguos
- Complexidade de fallbacks vale a pena?
  - O fluxo precisa ser observável (telemetria), testável (golden tests) e controlado por flags/feature-toggles

---

## Tabela-Resumo das Melhorias

| Ponto de Melhoria                     | Impacto Principal                   | Esforço |
| ------------------------------------- | ----------------------------------- | -------- |
| Refatorar "God Class" EstagiarioAgent | Manutenibilidade, Testabilidade     | Alto     |
| Externalizar Config/Constantes        | Flexibilidade, Segurança           | Baixo    |
| Injeção de Dependência (DB)        | Testabilidade, Desacoplamento       | Médio   |
| Parsing JSON do LLM centralizado      | Robustez, Redução de Duplicação | Baixo    |
| Prompts Estruturados                  | Manutenibilidade, Agilidade         | Médio   |
| Rate Limiting Global (Redis)          | Robustez em Produção              | Médio   |
| Otimizar `_fetch_clusters`          | Performance, Consumo de Memória    | Médio   |
| Evitar Chamadas Repetidas ao DB       | Performance, Eficiência            | Baixo    |

---

## Incrementos Recentes (já implementados)

- Edição agentic robusta (até 10 iterações/hora): SPEC do LLM → busca com priorities/tags/keywords dinâmicas → pick de candidatos pelo LLM → aplicação (1 ou N) com confirmação no DB e logs completos
- Resolução de tag/prioridade: frase explícita → contexto do cluster → frase+catálogo (LLM)
- Logs: exibição dos RAWs do LLM (understand_edit, pick-best, choose_tag/priority) e confirmação DB pós-CRUD
