## BTG AlphaFeed

Plataforma de inteligência de mercado que transforma alto volume de notícias em um feed orientado a eventos (clusters) para Special Situations.

### O que é (visão executiva)
- Identifica o fato gerador por trás de múltiplas notícias e consolida em um único evento.
- Classifica por prioridade (P1 crítico, P2 estratégico, P3 monitoramento) e por categoria temática (tags).
- Gera resumos executivos no tamanho certo por prioridade (P1 longo, P2 médio, P3 curto).
- Oferece visualização por data, filtros e drill-down para as fontes originais.

### Como funciona na prática
- Carregue PDFs/JSONs de crawlers (upload manual ou via API) → são salvos como artigos brutos.
- O processamento orquestrado agrupa por fato gerador, classifica e gera resumos.
- O frontend exibe o feed por data, com filtros de prioridade e tags dinâmicas vindas dos dados reais.

### Filtros e visualização (frontend)
- Seletor de data no topo: alterna entre hoje e datas históricas (tudo GMT-3).
- Filtros: prioridade (P1/P2/P3) e tags dinâmicas (derivadas dos clusters reais).
- P3 Monitoramento: cards consolidados por tag com lista em bullets; clique abre modal com detalhes.
- Deep-dive: modal por evento com resumo, fontes e abas (chat com cluster e gerenciamento).

### Tags e Prioridades (como configurar)
- Tags oficiais: editar `backend/prompts.py` em `TAGS_SPECIAL_SITUATIONS` (única fonte da verdade).
- Prioridades: editar `LISTA_RELEVANCIA_HIERARQUICA` no mesmo arquivo para ajustar critérios e exemplos.
- O mapeamento determinístico assunto ➜ (prioridade, tag) é gerado a partir dessas estruturas.

### Pipeline (passo a passo)
1) Ingestão: `load_news.py` lê PDFs/JSONs e grava artigos brutos (status `pendente`).
2) Processamento inicial: extrai dados, gera embeddings e marca `pronto_agrupar`.
3) Agrupamento: cria/atualiza clusters por fato gerador (modo em lote ou incremental automático).
4) Classificação e Resumos: define prioridade/tag e gera resumo no tamanho certo.
5) Exposição: API `FastAPI` alimenta o frontend; CRUD e endpoints admin.

```mermaid
graph TD
  A[Upload PDFs/JSON<br/>load_news.py] --> B[(PostgreSQL<br/>artigos_brutos: pendente)]
  B --> C[process_articles.py<br/>Etapa 1: processar artigos]
  C --> D[(artigos_brutos: pronto_agrupar)]
  D --> E[process_articles.py<br/>Etapa 2: agrupar (pivot auto))]
  E --> F[Etapa 3: classificar e resumir]
  F --> G[(clusters_eventos + resumos)]
  G --> H[FastAPI /api/feed]
  H --> I[Frontend /frontend]
  J[Admin: upload-file<br/>processar-pendentes] --> H
```

### LLMs e prompts (o que roda e para quê)
- Extração e triagem inicial: `PROMPT_EXTRACAO_PERMISSIVO_V8`.
- Agrupamento em lote: `PROMPT_AGRUPAMENTO_V1`.
- Agrupamento incremental (novas notícias do dia): `PROMPT_AGRUPAMENTO_INCREMENTAL_V1`.
- Resumo executivo por prioridade: `PROMPT_RESUMO_FINAL_V3` e `PROMPT_RADAR_MONITORAMENTO_V1` (bullets P3).
- Sanitização (gatekeeper): `PROMPT_SANITIZACAO_CLUSTER_V1`.
- Chat com cluster: `PROMPT_CHAT_CLUSTER_V1`.
- Onde ajustar: `backend/prompts.py` (textos, tags, prioridades). API key via `backend/.env` (`GEMINI_API_KEY`).

### Arquitetura em 1 minuto
- Backend FastAPI + SQLAlchemy (PostgreSQL 5433)
- Frontend estático em `backend/frontend`
- Orquestração por scripts CLI para ingestão e processamento

## Guia Rápido

### Pré-requisitos
- Anaconda instalado; usar o ambiente `pymc2`
- PostgreSQL local ativo na porta `5433`
- `backend/.env` com variáveis mínimas:
  ```env
  DATABASE_URL="postgresql+psycopg2://postgres_local@localhost:5433/devdb"
  GEMINI_API_KEY="<sua_chave_gemini>"
  ```

### 1) Ativar ambiente e entrar no projeto
```bash
conda activate pymc2
cd "C:\Users\marcos.silva\OneDrive - ENFORCE GESTAO DE ATIVOS S.A\jupyter\projetos\novo-topnews\pdfs\silva-front\btg_alphafeed"
```

### 2) Comandos essenciais
- Upload manual de PDFs/JSON (diretório completo):
  ```bash
  python load_news.py --dir ../pdfs --direct --yes
  ```
- Upload de um arquivo específico:
  ```bash
  python load_news.py --file ../pdfs/arquivo.pdf --direct --yes
  ```
- Processar artigos (extração → agrupamento → resumos):
  ```bash
  python process_articles.py
  ```
- Iniciar o backend (use apenas se não houver outro servidor rodando):
  ```bash
  python start_dev.py
  ```
- Acesso rápido: Frontend `http://localhost:8000/frontend` | Docs `http://localhost:8000/docs` | Health `http://localhost:8000/health`

## Sincronizar Banco Local → Heroku (Incremental)
Rodar a partir da pasta `silva-front` ou `btg_alphafeed`:
```bash
conda activate pymc2
python -m btg_alphafeed.migrate_incremental \
  --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" \
  --dest   "postgres://<usuario>:<senha>@<host>:5432/<db>" \
  --include-logs --include-chat
```
- Opções úteis:
  - `--no-update-existing`: não atualiza registros existentes (apenas insere novos)
  - `--since <ISO-UTC>`: inicia a partir de um timestamp específico
  - `--meta-file btg_alphafeed/last_migration.txt`: armazena o último timestamp migrado
  - `--only clusters,artigos,logs`: restringe entidades

## Tarefas Comuns
- Reexecutar pipeline completo (ingestão + processamento):
  ```bash
  python load_news.py --dir ../pdfs --direct --yes && python process_articles.py
  ```
- Migração completa (one-shot):
  ```bash
  python -m btg_alphafeed.migrate_databases --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" --dest "postgres://<usuario>:<senha>@<host>:5432/<db>"
  ```
- Limpar banco (script interativo, com backup):
  ```bash
  python limpar_banco.py
  ```
- Ver estado da API e DB:
  ```bash
  curl http://localhost:8000/health
  ```

## Playbooks (cenários prontos)

### 1) Rodar o dia do zero (ingestão PDFs/JSON + processamento + backend)
```bash
conda activate pymc2
cd btg_alphafeed
python load_news.py --dir ../pdfs --direct --yes
python process_articles.py
# iniciar backend somente se necessário
python start_dev.py
```

### 2) Apenas ingestão de JSON (sem LLM) e processamento
```bash
conda activate pymc2
cd btg_alphafeed
python load_news.py --dir ../pdfs --direct --yes
python process_articles.py
```

### 3) Reprocessar apenas pendentes já carregados
```bash
conda activate pymc2
cd btg_alphafeed
python process_articles.py
```

### 4) Ingestão incremental de PDFs durante o dia + agrupamento incremental
```bash
conda activate pymc2
cd btg_alphafeed
# novas páginas/PDFs na pasta ../pdfs
python load_news.py --dir ../pdfs --direct --yes
python process_articles.py
```

### 5) Sincronizar local → Heroku (incremental, com logs e chat)
```bash
conda activate pymc2
cd silva-front
python -m btg_alphafeed.migrate_incremental \
  --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" \
  --dest   "postgres://<usuario>:<senha>@<host>:5432/<db>" \
  --include-logs --include-chat
```

### 6) Verificar data sem dados (sanidade)
```bash
curl "http://localhost:8000/api/feed?data=2099-01-01"
# Esperado: métricas zeradas e lista vazia (sem dados de teste)
```

## Regras de Negócio e Convenções
- Tags: usar apenas as definidas em `backend/prompts.py` (`TAGS_SPECIAL_SITUATIONS`)
- JSONs de crawlers: ingestão direta; LLM só na fase de agrupamento/síntese
- `process_articles.py`: orquestra e chama a lógica do backend; sem regras de negócio próprias
- Status dos artigos: `pendente` → `pronto_agrupar` → `processado`
- Prioridades e resumos: P1 (longo), P2 (médio), P3 (curto)

## Endpoints principais
- `GET /api/feed?data=YYYY-MM-DD`
- `POST /admin/processar-pendentes`
- `POST /api/admin/upload-file` e `GET /admin/upload-progress/{file_id}`
- `GET /health`
- Frontend servido em `/frontend`

## Dicas de Ambiente
- Sempre usar Anaconda Prompt e `conda activate pymc2`
- Porta padrão do Postgres local: `5433`
- Evite subir o backend se já existir um servidor rodando

## Troubleshooting (rápido)
- Sem `GEMINI_API_KEY`: PDFs são ingeridos como 1 artigo por página (fallback)
- Conexão DB falhando: confirme porta `5433` e `DATABASE_URL`
- Sem artigos pendentes: rode primeiro o upload (`load_news.py`)
- API offline: use o modo `--direct` do `load_news.py`

## Testes
```bash
python tests/test_imports.py
python test_fluxo_completo.py
```

## Segurança
- Nunca commitar `.env` ou credenciais
- Evite colar URLs de produção com usuário/senha em documentos/commits

## Formatos suportados (resumo)
- JSON de crawlers: campos típicos `id_hash`, `titulo`, `texto_completo`, `link`, `fonte`, `data_publicacao`
- PDF: OCR + LLM quando disponível; fallback 1 artigo por página

## Referências rápidas
- Upload: `python load_news.py --dir ../pdfs --direct --yes`
- Processar: `python process_articles.py`
- Backend: `python start_dev.py`
- Sync Heroku: `python -m btg_alphafeed.migrate_incremental --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" --dest "postgres://<usuario>:<senha>@<host>:5432/<db>" --include-logs --include-chat`

---

## Documentação para LLMs (manutenção e navegação do código)

### Mapa de pastas (o que cada uma faz)
- `btg_alphafeed/backend/main.py`: aplicação FastAPI, rotas principais (`/api/feed`, admin, upload, health), serve frontend e orquestra background tasks.
- `btg_alphafeed/backend/database.py`: engine, sessões, modelos SQLAlchemy, helpers de conexão e utilidades de schema.
- `btg_alphafeed/backend/crud.py`: operações de banco de dados (artigos, clusters, associações, atualizações de status, métricas, logs).
- `btg_alphafeed/backend/processing.py`: pipeline de processamento unitário (embeddings, similaridade, processamento de artigo, resumo de cluster, utilitários de cluster).
- `btg_alphafeed/backend/models.py`: modelos Pydantic para request/response.
- `btg_alphafeed/backend/prompts.py`: fonte da verdade de `TAGS_SPECIAL_SITUATIONS`, `LISTA_RELEVANCIA_HIERARQUICA` e todos os prompts de LLM.
- `btg_alphafeed/backend/utils.py`: utilidades gerais (datas GMT-3, etc.).
- `btg_alphafeed/backend/collectors/file_loader.py`: classe `FileLoader` usada por `load_news.py` para ingerir PDFs/JSONs.
- `btg_alphafeed/frontend/index.html|script.js|style.css`: UI do feed, seletor de data, modal de deep-dive, filtros dinâmicos.
- `btg_alphafeed/frontend/settings.html|settings.js`: UI administrativa/CRUD e operações de manutenção.
- `btg_alphafeed/load_news.py`: CLI para ingestão de PDFs/JSONs (salva artigos brutos, com `--direct` para DB).
- `btg_alphafeed/process_articles.py`: orquestrador do pipeline (processar → agrupar → classificar/resumir). Não conter regra de negócio própria.
- `btg_alphafeed/migrate_incremental.py`: sync incremental local → Heroku (idempotente, com filtros `--only`, `--include-logs`, `--include-chat`).
- `btg_alphafeed/migrate_databases.py`: migração completa (one-shot) local → Heroku.
- `btg_alphafeed/limpar_banco.py`: limpeza seletiva com backup.

### Fluxos críticos (pontos de extensão)
- Ingestão: estender `backend/collectors/file_loader.py` para novas fontes/formatos.
- Classificação/Tags: alterar apenas `backend/prompts.py` e manter coerência com `TAGS_SPECIAL_SITUATIONS`.
- Prioridade/Resumo: `backend/prompts.py` (PROMPT_RESUMO_*), tamanho conforme P1/P2/P3.
- Agrupamento incremental: `PROMPT_AGRUPAMENTO_INCREMENTAL_V1` e lógica de pivot automático em `process_articles.py`.
- API/Endpoints: adicionar rotas em `backend/main.py` e delegar CRUD para `backend/crud.py`.

### Regras de contribuição (para evitar duplicação e lógica fora do lugar)
- Orquestração em scripts (CLI): `load_news.py` e `process_articles.py` apenas chamam o backend.
- Lógica de negócio: `backend/processing.py` + `backend/crud.py` (nunca em CLI nem em rotas diretamente).
- Esquema de dados (DB): `backend/database.py` (modelos/relacionamentos) e migrations externas quando necessário.
- Prompts/taxonomia: `backend/prompts.py` (fonte única). O frontend consome tags vindas dos dados reais (sem listas fixas).

### Consulta rápida de responsabilidades
- Gerar resumo de um cluster: `backend/processing.py::gerar_resumo_cluster`
- Associar artigo a cluster: `backend/crud.py::associate_artigo_to_cluster`
- Buscar feed por data: `backend/main.py::get_feed`
- Upload via API: `backend/main.py::upload_file_endpoint` e progresso em `upload_progress`
- Processar pendentes (admin): `backend/main.py::processar_artigos_pendentes` → chama funções do pipeline

