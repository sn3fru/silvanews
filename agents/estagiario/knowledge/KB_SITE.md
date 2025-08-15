# KB do Estagiário — Guia de Uso Interno (para o Agente)

Este documento descreve como o sistema funciona (dados, prioridades/tags, consultas ao banco) para orientar o agente na tomada de ações sem precisar enviar todo o contexto ao LLM a cada pergunta.

## 1) Visão Geral do Fluxo
- Ingestão → `artigos_brutos` (status: `pendente`)
- Processamento inicial (extrai campos, valida, embedding) → `pronto_agrupar`
- Agrupamento (eventos) → `clusters_eventos` (associa artigos aos clusters)
- Classificação + Resumo por prioridade/tag (P1, P2, P3) → `clusters_eventos.resumo_cluster`
- Priorização Executiva Final (reclassificação rígida)
- API/Frontend consomem os clusters do dia

## 2) Modelo de Dados (tabelas principais)
### 2.1 `artigos_brutos`
- Campos-chave: `id`, `texto_bruto`, `titulo_extraido`, `texto_processado`, `jornal`, `data_publicacao`, `status` (pendente|processado|irrelevante|erro), `tag`, `prioridade`, `embedding`, `cluster_id`, `created_at`, `processed_at`.
- Significado: artigo "raw" e/ou processado. Quando associados a um cluster, apontam para `clusters_eventos.id`.

### 2.2 `clusters_eventos`
- Campos-chave: `id`, `titulo_cluster`, `resumo_cluster`, `tag`, `prioridade`, `embedding_medio`, `status` (ativo), `total_artigos`, `created_at`, `updated_at`.
- Significado: evento/agregado de notícias (fato gerador). É o que aparece no feed.

### 2.3 `sinteses_executivas`
- Síntese do dia com métricas agregadas.

### 2.4 Chat (por cluster)
- `chat_sessions` (por cluster), `chat_messages` (mensagens por sessão/cluster)

### 2.5 Estagiário (novo)
- `estagiario_chat_sessions`: `id`, `data_referencia`, timestamps
- `estagiario_chat_messages`: `id`, `session_id`, `role` (user|assistant|system), `content`, `timestamp`

## 3) Prioridades e Tags
- Prioridades: `P1_CRITICO`, `P2_ESTRATEGICO`, `P3_MONITORAMENTO`, `IRRELEVANTE` (detalhes em `backend/prompts.py`)
- Tags (fonte da verdade em `backend/prompts.py::TAGS_SPECIAL_SITUATIONS`), ex.: Jurídico, M&A, Mercado de Capitais, Política Econômica, Internacional, Tecnologia, etc.
- Regras: P1/P2/P3 são definidas por gatilhos objetivos; P3 é a base (contexto), P1 é acionável agora.

## 4) Consultas Típicas ao Banco
A data retorna clusters/estatísticas do dia. Use `func.date(created_at) == <data>` para filtrar por dia.

### 4.1 Contar clusters irrelevantes do dia
```sql
SELECT COUNT(*)
FROM clusters_eventos
WHERE DATE(created_at) = :data
  AND status = 'ativo'
  AND (prioridade = 'IRRELEVANTE' OR tag = 'IRRELEVANTE');
```

### 4.2 Buscar clusters por prioridade (com resumo)
```sql
SELECT id, titulo_cluster, resumo_cluster, tag, prioridade, created_at
FROM clusters_eventos
WHERE DATE(created_at) = :data
  AND status = 'ativo'
  AND prioridade = :prioridade -- 'P1_CRITICO' | 'P2_ESTRATEGICO' | 'P3_MONITORAMENTO'
ORDER BY created_at DESC
LIMIT :limit OFFSET :offset;
```

### 4.3 Buscar clusters por palavras-chave (título/resumo)
```sql
SELECT id, titulo_cluster, resumo_cluster, tag, prioridade
FROM clusters_eventos
WHERE DATE(created_at) = :data
  AND status = 'ativo'
  AND (
    LOWER(titulo_cluster) LIKE :kw OR LOWER(resumo_cluster) LIKE :kw
  )
ORDER BY created_at DESC
LIMIT 50;
```
- Para busca acento-insensível, normalizar a string no app e montar `:kw` com `%termo%`.

### 4.4 Contar P1/P2/P3 do dia
```sql
SELECT prioridade, COUNT(*)
FROM clusters_eventos
WHERE DATE(created_at) = :data
  AND status = 'ativo'
GROUP BY prioridade;
```

### 4.5 Listar clusters com/tag específica
```sql
SELECT id, titulo_cluster, tag, prioridade
FROM clusters_eventos
WHERE DATE(created_at) = :data
  AND status = 'ativo'
  AND tag = :tag
ORDER BY created_at DESC;
```

### 4.6 Listar artigos de um cluster (títulos/fontes/URLs)
```sql
SELECT a.id, a.titulo_extraido, a.jornal, a.url
FROM artigos_brutos a
WHERE a.cluster_id = :cluster_id
ORDER BY a.created_at DESC;
```

## 5) Tools do Agente (contratos)
Para economizar tokens, o LLM deve chamar tools com entradas/saídas específicas.

### 5.1 Tool: `db_query`
- Entrada:
```json
{
  "sql": "SELECT ... WHERE DATE(created_at) = :data AND ...",
  "params": {"data": "YYYY-MM-DD"}
}
```
- Regras:
  - A tool executa a query e retorna linhas como `[{"col": val, ...}]`.
  - Não aceita comandos DDL/DML fora de SELECT.
  - Deve ser usada quando precisar de flexibilidade total de consulta.

### 5.2 Tool: `fetch_clusters`
- Entrada:
```json
{"date": "YYYY-MM-DD", "priority": "P1_CRITICO|P2_ESTRATEGICO|P3_MONITORAMENTO|null", "page": 1, "page_size": 50}
```
- Saída: `{ "clusters": [...], "paginacao": {...} }` (idêntico a `/api/feed?data=...&priority=...`)
- Use para paginação/consulta padrão.

### 5.3 Tool: `count_irrelevantes`
- Entrada: `{ "date": "YYYY-MM-DD" }`
- Saída: `{ "count": N }`
- Implementa a query precisa da seção 4.1.

## 6) Estratégia de Raciocínio do Agente
1. Interpretar a pergunta → extrair data (padrão: hoje), prioridade (se houver), palavras-chave.
2. Se a pergunta for contagem/estatística objetiva → usar tools de contagem/agrupamento (ex.: `count_irrelevantes`).
3. Se a pergunta exigir listagem/filtragem por prioridade → usar `fetch_clusters` por prioridade e/ou `db_query` para filtros de texto.
4. Montar resposta concisa e útil em Markdown; incluir amostra (títulos + resumos) quando listar itens e uma seção de Fontes com `[ID] Título — URL (Jornal)`.
5. Registrar pergunta/resposta no chat do Estagiário (sessão do dia).

## 7) Exemplos de Uso (para o Agente)
- “Quantas notícias irrelevantes hoje?”
  - Chamar `count_irrelevantes` com `date=today` → retornar o número.
- “Promoções de carros até 200 mil?”
  - Buscar clusters do dia (`fetch_clusters` sem prioridade), filtrar por palavras-chave indicativas e preços (regex simples) no app.
- “Impactos P1 EUA–Rússia?”
  - `fetch_clusters` com `priority=P1_CRITICO`, filtrar por palavras (EUA, Rússia, Putin, Kremlin) no título/resumo, sintetizar bullets.
