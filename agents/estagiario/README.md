## Agente "Estagiário" v3 — Gemini Function Calling + Self-Critique

O Estagiário é um agente de pesquisa que responde perguntas sobre as notícias do dia (e de dias anteriores) usando Gemini Function Calling nativo com self-critique loop.

### Arquitetura v3

```
Pergunta do usuário (header bar)
    ↓
EstagiarioAgent.answer()
    ↓
EstagiarioExecutor.run()
    ↓
    ├── Gemini generate_content() com tools declaradas via genai.protos.Tool
    ├── Function Calling Loop (max 15 iterações, budget 10 tool calls)
    │   ├── list_cluster_titles() → visão geral
    │   ├── query_clusters() → filtros por keyword/prioridade
    │   ├── get_cluster_details() → aprofundar cluster
    │   ├── query_clusters_range() → busca multi-dia (max 7 dias)
    │   ├── obter_textos_brutos_cluster() → textos originais
    │   └── buscar_na_web() → dados em tempo real
    ├── Resposta em Markdown
    └── Self-Critique Loop (max 2 retries)
        ├── Avalia nota 1-5 (específico? endereça a pergunta? fontes?)
        └── Se nota < 4 → re-prompta com feedback
```

### Ferramentas disponíveis

| Tool | Descrição | Fonte |
|------|-----------|-------|
| `list_cluster_titles` | Lista todos os clusters do dia (id, título, tags, prioridade) | Local |
| `query_clusters` | Busca clusters com filtros (prioridade, keywords) | Local |
| `get_cluster_details` | Detalhes completos de um cluster (artigos, fontes) | Local |
| `query_clusters_range` | Busca clusters em intervalo de datas (max 7 dias) | Local |
| `obter_textos_brutos_cluster` | Textos originais dos artigos (max 3000 chars cada) | Reuso do Resumo |
| `buscar_na_web` | Busca web em tempo real via Tivaly API | Reuso do Resumo |

### Diferenças v2 → v3

| Aspecto | v2 | v3 |
|---------|----|----|
| Tool dispatch | JSON parsing manual (regex) | Gemini Function Calling nativo |
| Qualidade | Sem validação | Self-critique loop (nota 1-5, max 2 retries) |
| Temporal | Apenas dia atual | Multi-dia (query_clusters_range, max 7 dias) |
| max_output_tokens | 2048 | 16384 |
| UI | Card injetado no feed | Input no header bar |
| Tools | 5 (1 broken, 1 write) | 6 (todas read-only, reuso do Resumo) |

### Constantes

| Constante | Valor | Descrição |
|-----------|-------|-----------|
| `_MAX_ITERATIONS` | 15 | Rounds no function calling loop |
| `_MAX_TOOL_CALLS` | 10 | Budget de chamadas de ferramentas |
| `_MAX_CRITIQUE_RETRIES` | 2 | Tentativas de melhoria via self-critique |
| `_MAX_OUTPUT_TOKENS` | 16384 | Teto de tokens de saída |
| `_MAX_RANGE_DAYS` | 7 | Máximo de dias em query_clusters_range |

### Endpoints FastAPI (inalterados)

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/api/estagiario/start` | Inicia sessão de chat |
| POST | `/api/estagiario/send` | Envia pergunta e recebe resposta |
| GET | `/api/estagiario/messages/{session_id}` | Histórico de mensagens |

### Arquivos

| Arquivo | Responsabilidade |
|---------|-----------------|
| `agent.py` | Interface pública (answer, answer_with_context) |
| `executor.py` | Function calling loop + self-critique |
| `prompts.py` | System prompt + critique prompt |
| `tools/definitions.py` | Implementação das tools + Gemini schemas + dispatcher |
| `tools/executor.py` | Re-export (backward compat) |
| `knowledge/KB_SITE.md` | Knowledge base interna (modelo de dados, prioridades) |

### Configuração

- Requer `GEMINI_API_KEY` para o modelo LLM (Gemini 2.0 Flash)
- Opcional: `TIVALY_API_KEY` para busca web
- Reutiliza CRUDs e modelos do backend existente
