## BTG AlphaFeed

Plataforma de inteligência de mercado que transforma alto volume de notícias em um feed orientado a eventos (clusters) para Special Situations, com suporte para notícias nacionais e internacionais.

### O que é (visão executiva)

- Identifica o fato gerador por trás de múltiplas notícias e consolida em um único evento.
- Classifica por prioridade (P1 crítico, P2 estratégico, P3 monitoramento) e por categoria temática (tags).
- Gera resumos executivos no tamanho certo por prioridade (P1 longo, P2 médio, P3 curto).
- Oferece visualização por data, filtros e drill-down para as fontes originais.
- **NOVO**: Separação entre notícias nacionais e internacionais com tags e critérios de priorização específicos.

### Como funciona na prática

- Carregue PDFs/JSONs de crawlers (upload manual ou via API) → são salvos como artigos brutos com **texto original completo** preservado.
- O processamento orquestrado agrupa por fato gerador, classifica e gera resumos dos **clusters** (não das notícias individuais).
- O frontend exibe o feed por data, com filtros de prioridade e tags dinâmicas vindas dos dados reais.

### Novidades recentes (pipeline mais rigoroso)

- **Suporte a notícias internacionais**: Sistema de abas Brasil/Internacional no frontend com:
  - Detecção automática do tipo de fonte (nacional/internacional) baseada no jornal
  - Tags específicas para contexto internacional (ex: "Global M&A", "Central Banks and Monetary Policy")
  - Critérios de priorização adaptados para mercado global (valores em dólares, empresas Fortune 500)
  - Filtros independentes por tipo de fonte na API
- **Preservação do texto original**: O `texto_bruto` dos PDFs é **NUNCA alterado** durante o processamento, garantindo acesso ao conteúdo original completo.
- **Resumos de clusters**: O `texto_processado` contém resumos dos **clusters de eventos**, não de notícias individuais.
- Endurecimento do `PROMPT_EXTRACAO_PERMISSIVO_V8`: lista de rejeição ampliada (crimes comuns, casos pessoais, fofoca/entretenimento, esportes, política partidária, efemérides e programas sociais sem tese) e gating P1/P2/P3 mais duro.
- Priorização Executiva Final integrada: etapa adicional pós-resumo/pós-agrupamento que reclassifica como P1/P2/P3/IRRELEVANTE com justificativa e ação recomendada (`PROMPT_PRIORIZACAO_EXECUTIVA_V1`).
- Nova Etapa 4 – Consolidação Final de Clusters: reagrupamento conservador de clusters do dia usando `PROMPT_CONSOLIDACAO_CLUSTERS_V1` com base em títulos, tags e prioridades já atribuídos. A maioria dos clusters permanece inalterada; quando há duplicidade (p.ex. variações de "PGFN arrecadação recorde"), a etapa sugere merges, move artigos para um destino, ajusta título/tag/prioridade quando necessário e arquiva (soft delete) os duplicados.
- Robustez: ajustes para evitar truncamento do LLM e JSON quebrado — lotes menores, campos de resumo encurtados e fallback de parsing.
  - Incremental: lotes de até 100, `titulos_internos` reduzido a 10 por cluster, heurística que impede criação de múltiplos clusters genéricos (ex.: "Notícia sem título").
  - Priorização: lotes de até 40, `resumo_final` enviado truncado a ~240 caracteres, `max_output_tokens` 8192 para batched.
  - Consolidação: lotes de até 50; parsing de sugestões tolerante a erros; fallback determinístico por título/tag.

### Filtros e visualização (frontend)

- **Abas Brasil/Internacional**: Separa notícias por tipo de fonte com filtros independentes.
- Card do Estagiário otimizado: design mais compacto com título e descrição na mesma linha.
- Seletor de data no topo: alterna entre hoje e datas históricas (tudo GMT-3).
- Filtros: prioridade (P1/P2/P3) e tags dinâmicas (derivadas dos clusters reais).
- P3 Monitoramento: cards consolidados por tag com lista em bullets; clique abre modal com detalhes.
- Deep-dive: modal por evento com resumo, fontes e abas (chat com cluster e gerenciamento).

### Tags e Prioridades (como configurar)

- **Configuração via Frontend**: Acesse `/frontend/settings.html` → aba "Prompts" para editar tags e prioridades de forma visual e intuitiva.
- **Persistência no Banco**: Tags e prioridades são agora armazenadas no PostgreSQL, permitindo edições em produção sem perda de dados.
- **Estrutura das Tags**: Cada tag tem nome, descrição, exemplos e ordem de exibição.
- **Estrutura das Prioridades**: Itens organizados por nível (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO) com descrições personalizáveis.
- **Fallback Automático**: O sistema carrega do banco de dados, mas mantém compatibilidade com as estruturas originais do `backend/prompts.py`.
- **Migração**: Use `python seed_prompts.py` para popular o banco com dados iniciais após criar as tabelas.

### Pipeline (passo a passo)

1) Ingestão
   - `load_news.py` chama `backend/collectors/file_loader.py`
   - PDFs: usa `PROMPT_EXTRACAO_PDF_RAW_V1` para extrair TEXTO COMPLETO ORIGINAL (sem resumo)
   - JSONs: ingeridos diretamente sem LLM
   - Salva como artigos brutos (status `pendente`) com `texto_bruto` preservado
2) Processamento inicial (Etapa 1)
   - `process_articles.py::processar_artigo_sem_cluster`
   - Valida dados, aplica heurísticas leves e gera embeddings (sem prompts/LLM)
   - Marca `pronto_agrupar`
3) Agrupamento (Etapa 2)
   - Lote: `process_articles.py::agrupar_noticias_com_prompt` → `PROMPT_AGRUPAMENTO_V1`
   - Incremental: `process_articles.py::agrupar_noticias_incremental` → `PROMPT_AGRUPAMENTO_INCREMENTAL_V2` (lotes ≤ 100; 10 títulos por cluster; heurística anti-duplicação para títulos genéricos)
4) Classificação e Resumo (Etapa 3)
   - `process_articles.py::classificar_e_resumir_cluster`
   - Classificação/Prioridade/Tag: `PROMPT_EXTRACAO_GATEKEEPER_V13`
   - Resumo do CLUSTER: `PROMPT_RESUMO_FINAL_V3` (salvo em `texto_processado` do cluster)
5) Priorização e Consolidação (Etapa 4)
   - Priorização executiva: `process_articles.py::priorizacao_executiva_final` → `PROMPT_PRIORIZACAO_EXECUTIVA_V1` (lotes ≤ 40; `resumo_final` ~240; `max_output_tokens` 8192)
   - Consolidação final: `process_articles.py::consolidacao_final_clusters` → `PROMPT_CONSOLIDACAO_CLUSTERS_V1` (lotes ≤ 50) + fallback determinístico (Jaccard por título e mesma tag)
6) Exposição: API `FastAPI` alimenta o frontend; CRUD e endpoints admin.

```mermaid
graph TD
  A[Upload PDFs/JSON<br/>load_news.py] --> B[(PostgreSQL<br/>artigos_brutos: pendente)]
  B --> C[process_articles.py<br/>Etapa 1: processar artigos]
  C --> D[(artigos_brutos: pronto_agrupar)]
  D --> E[process_articles.py<br/>Etapa 2: agrupar (pivot auto))]
  E --> F[Etapa 3: classificar e resumir]
  F --> F2[Etapa 4: priorização executiva]
  F2 --> G[(clusters_eventos + resumos + prioridades finais)]
  G --> H[FastAPI /api/feed]
  H --> I[Frontend /frontend]
  J[Admin: upload-file<br/>processar-pendentes] --> H
```

### LLMs e prompts (o que roda e para quê)

- Extração de PDFs: `PROMPT_EXTRACAO_PDF_RAW_V1`.
- Gatekeeper de relevância/priority/tag (clusters): `PROMPT_EXTRACAO_GATEKEEPER_V13`.
- Agrupamento em lote: `PROMPT_AGRUPAMENTO_V1` (lotes ≤ 60; `max_output_tokens` 32768).
- Agrupamento incremental (novas notícias do dia): `PROMPT_AGRUPAMENTO_INCREMENTAL_V2` (lotes ≤ 100; 10 títulos por cluster; `max_output_tokens` 32768).
- Resumo executivo por prioridade: `PROMPT_RESUMO_FINAL_V3`.
- Chat com cluster: `PROMPT_CHAT_CLUSTER_V1`.
- Priorização executiva (pós-pipeline): `PROMPT_PRIORIZACAO_EXECUTIVA_V1`.
- Consolidação final de clusters (Etapa 4): `PROMPT_CONSOLIDACAO_CLUSTERS_V1`.

### Busca Semântica (novo módulo)

- Pacote: `btg_alphafeed/semantic_search/` com:
  - `embedder.py`: geração de embeddings (`text-embedding-3-small` via OpenAI se disponível; fallback determinístico).
  - `store.py`: persistência em `semantic_embeddings` (tabela dedicada, não interfere no pipeline atual).
  - `search.py`: busca por similaridade de cosseno em memória (compatível sem pgvector).
  - `backfill_embeddings.py`: utilitário CLI para gerar embeddings dos artigos existentes.
- Integração com o agente Estagiário: nova tool `semantic_search(consulta, limite?, modelo?)` para consultas abertas.
- Como rodar o backfill:
  ```bash
  conda activate pymc2
  python -m btg_alphafeed.semantic_search.backfill_embeddings --limit 1000 --model text-embedding-3-small
  ```

### Agente Estagiário: plano → execução (agentic)

- O agente agora opera com camadas LLM para planejar e executar:
  1. Entender intenção (consultar notícias, ADMIN, EDIÇÃO no DB, ou ANÁLISE DE FEEDBACK)
  2. Se EDIÇÃO (trocar tag/prioridade):
     - Entende operação via LLM (JSON: operation/cluster_id/cluster_title/new_tag/new_priority)
     - Se não houver `new_tag`/`new_priority`, consulta o LLM com o CATÁLOGO do banco e o contexto do cluster para decidir a tag/prioridade corretas
     - Resolve o cluster por ID ou título parcial do dia e aplica via CRUD
  3. Se ANÁLISE DE FEEDBACK (ex.: "quais notícias têm reforço positivo?"):
     - Busca notícias com likes/dislikes do dia
     - Lista títulos e informações para ajuste de prompts
     - Fornece estatísticas de aprovação
  4. Se CONSULTA (ex.: "quero trocar de carro para um elétrico, tem promoção?"):
     - Pede ao LLM um SPEC JSON de busca (priorities/tags/keywords)
     - Coleta candidatos do DB, triagem via LLM, aprofunda top-K e sintetiza resposta

Endpoints do agente

- `POST /api/estagiario/start`, `POST /api/estagiario/send`, `GET /api/estagiario/messages/{session_id}`

Prompts opcionais/POC (não usados no pipeline padrão):

- `PROMPT_RESUMO_CRITICO_V1` (POC de resumo crítico)
- `PROMPT_RADAR_MONITORAMENTO_V1` (POC de bullets de radar P3)
- `PROMPT_AGRUPAMENTO_INCREMENTAL_V1` (substituído por `V2` no pipeline)
- `PROMPT_SANITIZACAO_CLUSTER_V1` (disponível como segunda linha de defesa; não integrado por padrão)
- `PROMPT_EXTRACAO_JSON_V1` (alias de `PROMPT_EXTRACAO_PERMISSIVO_V8`, mantido para compatibilidade)
- Onde ajustar: `backend/prompts.py` (textos, tags, prioridades). API key via `backend/.env` (`GEMINI_API_KEY`).

### Arquitetura em 1 minuto

- Backend FastAPI + SQLAlchemy (PostgreSQL 5433)
- **Estrutura de dados**: `artigos_brutos` (texto original dos PDFs) → `clusters_eventos` (resumos dos clusters)
  - **NOVO**: Coluna `tipo_fonte` em ambas as tabelas para separar notícias nacionais/internacionais
- **Preservação de dados**: `texto_bruto` nunca é alterado; `texto_processado` contém resumos dos clusters
- Frontend estático em `frontend/`
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

### 2) Migração do banco de dados (NOVO - executar uma vez)

Se você já tem um banco existente, execute a migração para adicionar suporte a notícias internacionais:

```bash
python add_tipo_fonte_migration.py
```

### 3) Comandos essenciais

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

  - Rodar somente a Etapa 4 (Priorização + Consolidação Final):

  ```bash
  python process_articles.py --stage 4
  ```

  - Rodar em modo em lote (em vez de incremental) e selecionar etapa:

  ```bash
  python process_articles.py --modo lote --stage all
  ```
- Iniciar o backend (use apenas se não houver outro servidor rodando):

  ```bash
  python start_dev.py
  ```
- Acesso rápido: Frontend `http://localhost:8000/frontend` | Docs `http://localhost:8000/docs` | Health `http://localhost:8000/health`

### Estimativa de Custos (LLM)

Para uma estimativa rápida de custos por etapa do pipeline, execute:

```bash
python estimativa_custos.py
```

O script simula tokens de entrada/saída por etapa usando as notícias no banco e imprime um comparativo por cenário de modelos.

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

### Replace do dia (produção) com reprocessamento local

Use quando você reprocessou o dia localmente (novos prompts) e quer substituir o dia em produção de forma limpa (sem manter clusters antigos do mesmo dia).

Passo a passo:

1. Reprocessar localmente o dia (mantém brutos, limpa processados de hoje e reprocessa o pipeline completo):

   ```bash
   conda activate pymc2
   cd btg_alphafeed
   python reprocess_today.py
   ```
2. Replace no destino (produção) APENAS do dia desejado:

   ```bash
   conda activate pymc2
   cd btg_alphafeed
   python migrate_replace_today.py \
     --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" \
     --dest   "postgres://<usuario>:<senha>@<host>:5432/<db>" \
     --day $(python -c "from datetime import date; print(date.today().isoformat())")
   ```

   O utilitário limpa no destino os dados do dia (desassocia artigos, remove clusters/alterações/chat/síntese do dia) e migra do origem os clusters/artigos/síntese do mesmo dia, forçando `cluster_id` dos artigos.
3. (Opcional) Rodar incremental normal para demais dias/logs/chat:

   ```bash
   python -m btg_alphafeed.migrate_incremental \
     --source "postgresql+psycopg2://postgres_local@localhost:5433/devdb" \
     --dest   "postgres://<usuario>:<senha>@<host>:5432/<db>" \
     --include-logs --include-chat
   ```

## Suporte a Notícias Internacionais (NOVO)

O sistema agora diferencia automaticamente entre fontes nacionais e internacionais:

**Detecção Automática de Fonte**:
- Jornais nacionais: Folha, Estadão, O Globo, Valor, etc.
- Jornais internacionais: NYT, WSJ, Financial Times, Bloomberg, etc.
- Default: nacional (para compatibilidade com dados existentes)

**Tags Internacionais Disponíveis**:
- Global M&A and Corporate Transactions
- Global Legal and Regulatory
- Sovereign Debt and Credit
- Global Distressed and Restructuring
- Global Capital Markets
- Central Banks and Monetary Policy
- Geopolitics and Trade
- Technology and Innovation

**Critérios de Priorização Internacional**:
- P1: Defaults soberanos > $5B, Chapter 11 de Fortune 500, mega-mergers > $20B
- P2: Mudanças de rating de países G20, M&As cross-border > $5B
- P3: Earnings regulares, indicadores econômicos, desenvolvimentos políticos

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

### Reprocessamento seletivo (do dia atual)

- Reverter clusters problemáticos (move artigos para `pronto_agrupar` e arquiva clusters):
  ```bash
  # Seleção automática por títulos genéricos (ex.: "Notícia sem título")
  python revert_bad_clusters.py
  # OU por IDs específicos
  python revert_bad_clusters.py --ids 8349,8350
  ```
- Reagrupar apenas os revertidos e concluir Etapas 3 e 4:
  ```bash
  python reprocess_incremental_today.py
  ```

### Novo (Protótipo) – Análise de Feedback para Ajuste de Prompt

- Agora é possível registrar like/dislike de notícias diretamente no feed (👍/👎 ao lado do título de cada card). O backend agrega esse feedback por cluster e expõe no `GET /api/feed` dentro do campo `feedback` de cada item: `{ likes, dislikes, last }`.
- Foi adicionado um protótipo de análise de feedback que sugere ajustes no prompt de agrupamento sem alterar os arquivos em produção. Ele gera um relatório com o diff do prompt proposto.

Rodar o protótipo de análise de feedback e gerar diff do prompt:

```bash
conda activate pymc2
python analisar_feedback_prompt.py --limit 200 --output reports/prompt_diff_feedback.md
```

Saída esperada:

- Arquivo `reports/prompt_diff_feedback.md` com:
  - Prompt atual
  - Prompt proposto (adiciona addendum baseado em padrões de like/dislike)
  - Diff (unified) entre os dois para revisão humana

Importante: este processo não altera `backend/prompts.py`. É apenas para estudo e validação.

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
  - Cada item do feed inclui `feedback: { likes, dislikes, last }` agregados por cluster
- `POST /admin/processar-pendentes`
- `POST /api/admin/upload-file` e `GET /admin/upload-progress/{file_id}`
- `GET /health`
- Frontend servido em `/frontend`

### Endpoints de BI e Feedback

- `GET /api/bi/series-por-dia?dias=30`
- `GET /api/bi/noticias-por-fonte?limit=20`
- `GET /api/bi/noticias-por-autor?limit=20`
- `POST /api/feedback?artigo_id=<id>&feedback=like|dislike`
- `GET /api/feedback?processed=`
- `POST /api/feedback/{id}/process`

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
- `btg_alphafeed/frontend/settings.html|settings.js`: UI administrativa/CRUD e operações de manutenção, com abas de BI (séries por dia, por fonte e por autor) e Feedback (like/dislike por artigo, com marcação de processado).
- `btg_alphafeed/load_news.py`: CLI para ingestão de PDFs/JSONs (salva artigos brutos, com `--direct` para DB).
- `btg_alphafeed/process_articles.py`: orquestrador do pipeline (processar → agrupar → classificar/resumir). Não conter regra de negócio própria.
- `btg_alphafeed/migrate_incremental.py`: sync incremental local → Heroku (idempotente, com filtros `--only`, `--include-logs`, `--include-chat`).
- `btg_alphafeed/migrate_databases.py`: migração completa (one-shot) local → Heroku.
- `btg_alphafeed/limpar_banco.py`: limpeza seletiva com backup.

### Fluxos críticos (pontos de extensão)

- Ingestão: estender `backend/collectors/file_loader.py` para novas fontes/formatos.
- Classificação/Tags: alterar apenas `backend/prompts.py` e manter coerência com `TAGS_SPECIAL_SITUATIONS`.
- Prioridade/Resumo: `backend/prompts.py` (PROMPT_RESUMO_*), tamanho conforme P1/P2/P3.
- Agrupamento incremental: `PROMPT_AGRUPAMENTO_INCREMENTAL_V2` (usa `titulos_internos` dos artigos de cada cluster no payload) e lógica de pivot automático em `process_articles.py`.
- API/Endpoints: adicionar rotas em `backend/main.py` e delegar CRUD para `backend/crud.py`.

### Regras de contribuição (para evitar duplicação e lógica fora do lugar)

- Orquestração em scripts (CLI): `load_news.py` e `process_articles.py` apenas chamam o backend.
- Lógica de negócio: `backend/processing.py` + `backend/crud.py` (nunca em CLI nem em rotas diretamente). A lógica de consolidação (Etapa 4) usa utilitários em `backend/crud.py` para merges seguros: `merge_clusters`, `update_cluster_title`, `update_cluster_priority`, `update_cluster_tags` e `soft_delete_cluster`.
- Esquema de dados (DB): `backend/database.py` (modelos/relacionamentos) e migrations externas quando necessário.
- Prompts/taxonomia: `backend/prompts.py` (fonte única). O frontend consome tags vindas dos dados reais (sem listas fixas).

### Consulta rápida de responsabilidades

- Gerar resumo de um cluster: `backend/processing.py::gerar_resumo_cluster`
- Associar artigo a cluster: `backend/crud.py::associate_artigo_to_cluster`
- Buscar feed por data: `backend/main.py::get_feed`
- Upload via API: `backend/main.py::upload_file_endpoint` e progresso em `upload_progress`
- Processar pendentes (admin): `backend/main.py::processar_artigos_pendentes` → chama funções do pipeline

## Agente Estagiário (beta)

- O que é: agente de consulta sobre as notícias do dia. Reusa ORM/CRUD do backend e pode sintetizar respostas em Markdown quando `GEMINI_API_KEY` estiver configurada.
- Modo ReAct (opcional): defina `ESTAGIARIO_REACT=1` no ambiente para ativar o executor que orquestra ferramentas formais (`agents/estagiario/tools`).
- Endpoints:
  - `POST /api/estagiario/start` — inicia sessão de chat do dia.
  - `POST /api/estagiario/send` — envia pergunta e retorna resposta do agente.
  - `GET /api/estagiario/messages/{session_id}` — histórico de mensagens.
