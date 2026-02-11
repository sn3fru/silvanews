# Busca Semantica (v1.x)

## Visao Geral

Modulo de busca semantica que permite consultas por significado (nao apenas texto exato) nos artigos do sistema. Usa embeddings vetoriais e similaridade de cosseno.

---

## Arquitetura

```
Consulta do usuario
      |
      v
Embedder (embedder.py)
  - OpenAI text-embedding-3-small (preferencial)
  - Fallback: hash deterministico
      |
      v
Vetor de query (float[])
      |
      v
Search (search.py)
  - Carrega todos embeddings do modelo
  - Calcula similaridade de cosseno
  - Retorna top-K resultados
      |
      v
Resultados: artigos com score de similaridade
```

---

## Componentes

### `embedder.py` - Geracao de Embeddings

| Classe/Funcao                 | Descricao                                    |
| ----------------------------- | -------------------------------------------- |
| `Embedder`                  | Abstracao de provedor de embeddings          |
| `Embedder.embed_text(text)` | Gera vetor de embedding para texto           |
| `Embedder.is_available()`   | Verifica se provedor esta configurado        |
| `get_default_embedder()`    | Singleton factory (retorna instancia padrao) |

**Provedores:**

- **OpenAI** (preferencial): `text-embedding-3-small` (requer `OPENAI_API_KEY`)
- **Fallback deterministico**: Hash-based, funciona sem API key

### `store.py` - Persistencia

| Funcao                                                              | Descricao                           |
| ------------------------------------------------------------------- | ----------------------------------- |
| `upsert_embedding_for_artigo(artigo_id, vector, provider, model)` | Salva/atualiza embedding            |
| `fetch_all_embeddings(model)`                                     | Busca todos embeddings de um modelo |

**Armazenamento:** Tabela `semantic_embeddings` (separada do campo `embedding` legado em `artigos_brutos`)

### `search.py` - Busca

| Funcao                                          | Descricao                        |
| ----------------------------------------------- | -------------------------------- |
| `semantic_search(query_vector, model, top_k)` | Busca semantica por similaridade |
| `_cosine_similarity(a, b)`                    | Calcula similaridade de cosseno  |

**Nota:** Busca em memoria (sem pgvector). Para escala, migrar para `pgvector`.

### `backfill_embeddings.py` - Utilitario

Script CLI para gerar embeddings dos artigos existentes (backfill).

```bash
python -m btg_alphafeed.semantic_search.backfill_embeddings \
  --limit 1000 \
  --model text-embedding-3-small
```

---

## Integracao com o Sistema

### Agente Estagiario

Ferramenta `semantic_search` disponivel no modo ReAct:

- Input: query (texto), limit (int), model (string)
- Gera embedding da query
- Busca artigos similares
- Retorna titulo, texto, data e score

### Pipeline de Processamento

- `backend/processing.py` gera embeddings simples (384d, hash-based) para clusterizacao
- O modulo de busca semantica usa embeddings mais ricos (OpenAI, 1536d) em tabela separada
- Os dois sistemas coexistem sem conflito

---

## Configuracao

| Variavel           | Descricao           | Obrigatoria               |
| ------------------ | ------------------- | ------------------------- |
| `OPENAI_API_KEY` | Chave da API OpenAI | Nao (fallback disponivel) |

---

## Limitacoes Atuais

1. **Busca em memoria**: Todos os embeddings sao carregados em Python para calcular similaridade
2. **Sem pgvector**: Nao usa extensao vetorial do Postgres (planejado para v2.0)
3. **Escala**: Funciona bem ate ~100k artigos; acima disso, migrar para pgvector
4. **Modelo fixo**: Usa apenas OpenAI ou fallback; sem suporte multi-provedor

---

## Evolucao Planejada (v2.0)

- Habilitar extensao `vector` no Postgres
- Adicionar coluna `embedding_v2 vector(768)` em `artigos_brutos`
- Criar indice HNSW para performance
- Busca diretamente no banco (sem carregar em memoria)
- Suporte a Gemini embeddings (768d)
