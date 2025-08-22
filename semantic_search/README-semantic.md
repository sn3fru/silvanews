## Busca Semântica — Guia de Operação

Este módulo adiciona busca semântica de notícias ao AlphaFeed. A ideia é transformar a consulta do usuário em um embedding de texto, comparar com os vetores dos artigos e retornar os mais próximos semanticamente.

### Visão geral

- Vetores dedicados ficam na tabela `semantic_embeddings` (não interfere no pipeline atual).
- O agente Estagiário expõe a tool `semantic_search(consulta, limite?, modelo?)` para consultas abertas.
- Geração de vetores acontece automaticamente no processamento de artigos (quando possível) e também pode ser feita via backfill.

### Pré‑requisitos

- Instale dependências: `openai` já está no `requirements.txt` do projeto.
- Opcional: defina `OPENAI_API_KEY` para usar o modelo `text-embedding-3-small`.
  - Sem a chave, há fallback determinístico (apenas para testes locais).

### Inicialização do schema

A nova tabela é criada pelo SQLAlchemy automaticamente. Garanta que as tabelas foram sincronizadas com um dos comandos abaixo:

```bash
# opção 1: inicializar via utilitário do backend
python -c "from backend.database import init_database; init_database()"

# opção 2: subir o backend local (também cria as tabelas)
python start_dev.py
```

### Geração de embeddings (duas formas)

1) Automática no pipeline: ao processar um artigo (`backend/processing.py`), o sistema tenta gerar um embedding semântico dedicado e persistir em `semantic_embeddings`.
2) Backfill manual (recomendado após ativação):

```bash
conda activate pymc2
python -m btg_alphafeed.semantic_search.backfill_embeddings --limit 1000 --model text-embedding-3-small
```

Observações:

- Com `OPENAI_API_KEY`, usa OpenAI. Sem a chave, gera vetores determinísticos (útil para testes, menor qualidade).

### Uso no Agente Estagiário (Recomendado)

O agente entende quando a consulta é aberta e pode preferir a busca semântica.

- Modo ReAct (se `ESTAGIARIO_REACT=1`):

  - O LLM chamará a tool:

  ```json
  {
    "action": "semantic_search",
    "action_input": { "consulta": "impacto da política fiscal no agronegócio", "limite": 5 }
  }
  ```
- Via API do Estagiário (sem expor ferramentas diretamente):

  1. Inicie sessão:

  ```bash
  curl -X POST http://localhost:8000/api/estagiario/start -H "Content-Type: application/json" -d "{}"
  ```

  2. Envie pergunta aberta (o agente decide usar semantic search quando fizer sentido):

  ```bash
  curl -X POST http://localhost:8000/api/estagiario/send \
       -H "Content-Type: application/json" \
       -d '{"session_id": 1, "message": "qual o impacto da nova política fiscal para o agronegócio?"}'
  ```

### Boas práticas

- Faça o backfill logo após habilitar a busca semântica para cobrir o histórico recente.
- Regule `--limit` de acordo com o volume de artigos.
- Mantenha `OPENAI_API_KEY` apenas em ambientes seguros.

### Roadmap (opcional)

- Habilitar `pgvector` e mover a similaridade para o Postgres (índice `ivfflat`, `vector_cosine_ops`).
- Expor endpoint REST dedicado, por exemplo: `GET /api/semantic-search?query=...&k=...`.

### Troubleshooting

- “Tabela não encontrada”: rode a inicialização do banco (ver seção de schema).
- “openai não encontrado”: instale requisitos e/ou atualize o ambiente `conda`.
- “LLM indisponível”: verifique `OPENAI_API_KEY`; o fallback funciona para testes, mas com qualidade menor.
