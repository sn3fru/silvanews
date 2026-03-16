## Agente "Estagiário" v2 — ReAct Agent

O Estagiário é um agente inteligente que responde perguntas sobre as notícias do dia usando um loop ReAct (Reasoning + Acting) com até 10 iterações, planejamento automático e retry de parsing.

### Arquitetura v2

```
Pergunta do usuário
    ↓
EstagiarioAgent.answer()
    ↓
EstagiarioExecutor.run()  ← Loop ReAct (max 10 iterações)
    ↓
    ├── Thought: "Vou listar os títulos do dia para planejar"
    ├── Action: list_cluster_titles()
    ├── Observation: [{id, titulo, tags, prioridade}, ...]
    ├── Thought: "Cluster #42 é relevante, vou aprofundar"
    ├── Action: get_cluster_details(cluster_id=42)
    ├── Observation: {artigos, resumo, fontes...}
    └── Action: Final Answer → Markdown
```

### Ferramentas disponíveis

| Tool | Descrição | Uso recomendado |
|------|-----------|-----------------|
| `list_cluster_titles` | Lista todos os clusters do dia (id, título, tags, prioridade) | SEMPRE usar primeiro para planejar |
| `query_clusters` | Busca clusters com filtros (prioridade, keywords) | Filtrar por critérios específicos |
| `get_cluster_details` | Detalhes completos de um cluster (artigos, fontes) | Aprofundar clusters selecionados |
| `update_cluster_priority` | Altera prioridade (unitário) | Apenas com confirmação do usuário |
| `semantic_search` | Busca semântica por artigos similares | Perguntas abertas sem keywords |

### Características v2

- **Planejamento**: O agente planeja na primeira iteração quais tools usar
- **Retry**: Parsing JSON com até 2 retries e fallback de extração
- **Máximo 10 iterações**: Resolve em 2-3 para perguntas simples, até 10 para complexas
- **Prompt robusto**: Instruções claras sobre protocolo, regras e formato

### Uso programático

```python
from agents.estagiario.agent import EstagiarioAgent

agent = EstagiarioAgent()
ans = agent.answer("Quais são as principais notícias de distressed hoje?")
print(ans.text)
```

### Uso com contexto de conversa

```python
history = [
    {"role": "user", "content": "O que aconteceu com a Petrobras?"},
    {"role": "assistant", "content": "A Petrobras anunciou..."},
    {"role": "user", "content": "E como isso afeta o mercado?"},
]
ans = agent.answer_with_context("E como isso afeta o mercado?", history)
```

### Endpoints FastAPI

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST | `/api/estagiario/start` | Inicia sessão de chat |
| POST | `/api/estagiario/send` | Envia pergunta e recebe resposta |
| GET | `/api/estagiario/messages/{session_id}` | Histórico de mensagens |

### Configuração

- Requer `GEMINI_API_KEY` para o modelo LLM (Gemini 2.5 Flash)
- Reutiliza CRUDs e modelos do backend existente
