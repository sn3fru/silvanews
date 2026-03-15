# Task de Implementação — Agrupamento e Priorização (1.A, 2.A, 2.B, 3.A)

Este documento define a **task de implementação** dos passos descritos em `docs/GUIA_IMPLEMENTACAO_AGRUPAMENTO_PRIORIZACAO.md`, em alinhamento com **.cursorrules** e com as **regras de ouro** abaixo. Cada passo deve ser executado na ordem; antes de cada um, fazer a pesquisa de impactos; ao final de cada um, atualizar a documentação e só então estudar o contexto para o próximo.

**Status:** As 8 tasks foram implementadas. A seção **"Resumo do que foi implementado"** (ao final) descreve o que foi feito em cada uma e em quais arquivos.

---

## Regras de ouro (obrigatórias)

1. **Pesquisar bem os impactos antes de implementar**
   - Ler os trechos relevantes de `docs/SYSTEM.md` e `docs/OPERATIONS.md` indicados no passo.
   - Identificar todos os arquivos e funções que serão alterados ou que chamam as funções alteradas (callers, testes, migrate).
   - Verificar leis imutáveis do `.cursorrules` (Gatekeeper V13, nacional/internacional, texto_bruto, v2 shadow) e que nenhuma alteração as viole.
   - Se houver mudança em `backend/database.py`, verificar regra de deploy: atualizar `migrate_incremental.py`, criar `migrate_<entidade>()`, flag `--include-*`, SQL para Heroku em `scripts/migrate_*.py`.

2. **Ao fim de cada implementação, atualizar a documentação**
   - Atualizar `docs/SYSTEM.md` com novas funções, prompts, tabelas ou fluxos que forem criados ou alterados.
   - Atualizar `docs/OPERATIONS.md` se houver novo endpoint, variável de ambiente ou comando relevante.
   - Opcionalmente anotar em `docs/GUIA_IMPLEMENTACAO_AGRUPAMENTO_PRIORIZACAO.md` que o passo X foi concluído (ex.: "✅ Passo 1 concluído em DD/MM/AAAA").

3. **Antes de começar a próxima implementação, estudar documentação e código**
   - Reler as seções atualizadas de SYSTEM.md e OPERATIONS.md.
   - Reler o passo atual e o próximo do Guia e deste documento.
   - Ver no código onde o próximo passo vai encaixar (funções, linhas aproximadas) para não implementar no escuro.

---

## Pré-requisito geral (antes do Passo 1)

- [ ] Ler `docs/SYSTEM.md` (pelo menos: Stack e Estrutura, Banco de Dados tabelas core, Pipeline v1 fluxo do main(), Funções críticas process_articles, processing.py, Prompts).
- [ ] Ler `docs/OPERATIONS.md` (Pipeline diário, Execução manual, Endpoints Admin/process-articles e Feed).
- [ ] Ler `docs/GUIA_IMPLEMENTACAO_AGRUPAMENTO_PRIORIZACAO.md` na íntegra.
- [ ] Ler `docs/PROBLEMA_AGRUPAMENTO_NOTICIAS.md` (Parte A problemas, Parte D detalhes técnicos).
- [ ] Ler `.cursorrules` (LEIS IMUTAVEIS, MAPA DE NAVEGACAO, DEPLOYMENT & SYNC, REGRAS DE CODIGO).

---

## Task 1 — Normalização de jornal e FONTES_FLASHES (Passo 1 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Ler `docs/SYSTEM.md` — onde está `backend/utils.py` (funções de datas, hashes, Gemini).
- [ ] Abrir `backend/utils.py`: ver assinaturas existentes, imports, se já existe algo para normalização de texto ou jornal.
- [ ] Buscar no código onde `jornal` é usado: `artigos_brutos.jornal`, `processar_lote_incremental`, `agrupar_noticias_com_prompt`, `backend/prompts.py` (PROMPT_AGRUPAMENTO*).
- [ ] Decidir onde colocar `FONTES_FLASHES`: `backend/prompts.py` (junto aos outros prompts) ou constante em `backend/utils.py`/config.
- [ ] Verificar que nenhuma lei imutável do .cursorrules é afetada (não mexe em Gatekeeper V13, tipo_fonte, texto_bruto, v2).

### Implementar

- Implementar conforme **Passo 1** do `docs/GUIA_IMPLEMENTACAO_AGRUPAMENTO_PRIORIZACAO.md`: `normalizar_jornal(nome: str) -> str`, constante `FONTES_FLASHES`, lógica (aliases, sem isenção para flashes).
- Escrever unit test para `normalizar_jornal` (Estadão, Valor, Brazil Journal, variações de maiúsculas/acentos). Deletar arquivo de teste após validar, se for arquivo temporário (conforme .cursorrules).

### Após implementar

- [ ] Atualizar `docs/SYSTEM.md`: na seção de utils ou de processamento, registrar `normalizar_jornal` e `FONTES_FLASHES` (onde ficaram).
- [ ] Se criou arquivo de teste temporário: deletar após uso.
- [ ] Antes da Task 2: reler SYSTEM.md atualizado; reler Passo 2 do Guia; no código, localizar `processar_lote_incremental` e onde são montados `novas_noticias` e `clusters_existentes_data`.

---

## Task 2 — Heurística da fonte na Etapa 2 (Passo 2 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Ler `docs/SYSTEM.md` — Funções críticas: `processar_lote_incremental`, `PROMPT_AGRUPAMENTO_INCREMENTAL_V2`.
- [ ] Abrir `process_articles.py`: função `processar_lote_incremental` (linhas ~1622–1680), onde são montados `novas_noticias` e `clusters_existentes_data`; onde o prompt é formatado e chamado.
- [ ] Abrir `backend/prompts.py`: localizar `PROMPT_AGRUPAMENTO_INCREMENTAL_V2`; ver placeholders (NOVAS_NOTICIAS, CLUSTERS_EXISTENTES); ver se há outro prompt de agrupamento (PROMPT_AGRUPAMENTO_V1) que também precise do bloco de jornais.
- [ ] Verificar se `get_artigos_by_cluster` está em crud.py e como é usado (ordem dos artigos, campos disponíveis como `jornal`).

### Implementar

- Implementar conforme **Passo 2** do Guia: incluir `jornal` (normalizado) em `novas_noticias`; incluir `jornais_no_cluster` em `clusters_existentes_data`; adicionar bloco no PROMPT_AGRUPAMENTO_INCREMENTAL_V2 (e, se aplicável, PROMPT_AGRUPAMENTO_V1); para FONTES_FLASHES injetar texto mais rigoroso, não isenção.

### Após implementar

- [ ] Atualizar `docs/SYSTEM.md`: na descrição da Etapa 2 / processar_lote_incremental, mencionar que o payload agora inclui `jornal` e `jornais_no_cluster` e que o prompt contém regra de mesmo jornal e variante para FONTES_FLASHES.
- [ ] Antes da Task 3: reler SYSTEM.md; reler Passo 3 do Guia; localizar em `process_articles.py` a função `processar_artigo_sem_cluster` e onde `noticia_data` é obtido e onde `metadados` é escrito/atualizado.

---

## Task 3 — Extração de fato gerador na Etapa 1 (Passo 3 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Ler `docs/SYSTEM.md` — processar_artigo_sem_cluster, Etapa 1, tabela artigos_brutos (metadados JSON).
- [ ] Abrir `process_articles.py`: `processar_artigo_sem_cluster` (linhas ~2339–2518); onde `noticia_data` é construído; onde `update_artigo_dados_sem_status` ou equivalente persiste dados; se `metadados` é passado ou atualizado em algum update.
- [ ] Abrir `backend/crud.py`: `update_artigo_dados_sem_status` (ou função que atualiza artigo processado) — ver se aceita/sobrescreve `metadados` e como.
- [ ] Abrir `backend/models.py`: ver padrão de modelos Pydantic existentes; onde definir `FatoGeradorContract` (no mesmo arquivo ou novo módulo de contratos).
- [ ] Decidir em falha de extração: status `erro` vs flag em metadados; quem reprocessa (job manual, retry na Etapa 1?). Garantir que artigos em erro não entrem na Etapa 2 (ver filtro de artigos em agrupar_noticias_incremental).

### Implementar

- Implementar conforme **Passo 3** do Guia: modelo Pydantic `FatoGeradorContract`; prompt `PROMPT_EXTRACAO_FATO_GERADOR_V1` em prompts.py; em processar_artigo_sem_cluster chamar LLM, validar com FatoGeradorContract; em falha não usar fallback titulo[:80], sinalizar reprocessamento; gravar em metadados['fato_gerador'] só quando válido. Compatibilidade: artigos já existentes podem usar fallback título até backfill (definir critério: ex. só se metadados já existir e não tiver fato_gerador).

### Após implementar

- [ ] Atualizar `docs/SYSTEM.md`: novo prompt PROMPT_EXTRACAO_FATO_GERADOR_V1; FatoGeradorContract; fluxo da Etapa 1 com extração de fato gerador e comportamento em falha.
- [ ] Atualizar `docs/OPERATIONS.md` se surgir variável de ambiente ou comando de reprocesso.
- [ ] Antes da Task 4: reler SYSTEM.md; reler Passo 4 do Guia; localizar em processar_lote_incremental e agrupar_noticias_com_prompt onde inserir fato_gerador no payload e onde obter referente do cluster.

---

## Task 4 — Etapa 2 usa fato gerador para comparação (Passo 4 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Ler SYSTEM.md — Etapa 2, processar_lote_incremental, agrupar_noticias_com_prompt (modo lote).
- [ ] Abrir `process_articles.py`: em processar_lote_incremental, estrutura de `novas_noticias` e `clusters_existentes_data` já alteradas na Task 2; onde adicionar `fato_gerador` por notícia e `fato_gerador_referente` por cluster; em agrupar_noticias_com_prompt, onde o lote é montado (noticias_lote_para_prompt) e se usa tema do cluster.
- [ ] Garantir compatibilidade: artigos sem fato_gerador (legado) usam fallback título apenas para exibição na Etapa 2; novos artigos sem fato_gerador não devem ter chegado à Etapa 2 (bloqueados na Task 3).

### Implementar

- Implementar conforme **Passo 4** do Guia: em novas_noticias incluir fato_gerador (de metadados ou fallback título para legado); em clusters_existentes_data usar primeiro artigo (ou gênese) para fato_gerador_referente; ajustar PROMPT_AGRUPAMENTO_INCREMENTAL_V2 e PROMPT_AGRUPAMENTO_V1 para deixar explícita a decisão por fato gerador.

### Após implementar

- [ ] Atualizar `docs/SYSTEM.md`: Etapa 2 passa a usar fato_gerador e fato_gerador_referente no payload; compatibilidade legado.
- [ ] Antes da Task 5: reler Passo 5 do Guia; localizar onde o referente do cluster é definido (primeiro artigo vs qualidade mínima; opcional artigo_genesis_id e migrate).

---

## Task 5 — Cluster imutável / referente com qualidade (Passo 5 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Ler SYSTEM.md — clusters_eventos, create_cluster, merge; process_articles onde cluster é criado (novo_cluster) e onde clusters_existentes_data é montado.
- [ ] Decidir Opção A (sem schema) vs Opção B (artigo_genesis_id + possível genesis_trancado). Se Opção B: ler .cursorrules "Se criar/alterar tabela em database.py"; abrir migrate_incremental.py e ver padrão de migrate_* e flags --include-*.
- [ ] Abrir backend/processing.py: find_or_create_cluster; onde embedding_medio é atualizado ao anexar; onde comparar com cluster (titulo_cluster, resumo_cluster).

### Implementar

- Implementar conforme **Passo 5** do Guia: referente por qualidade (fato_gerador length ≥ N ou uma substituição); Opção A em processar_lote_incremental e, se Opção B, schema + create_cluster + migrate_incremental. Em find_or_create_cluster comparar com referente de qualidade; não usar embedding_medio para decisão de anexar (ou manter atualização só para Etapa 4).

### Após implementar

- [ ] Se alterou database.py: atualizar migrate_incremental.py (import, migrate_*, flag, main()); fornecer SQL em scripts/migrate_*.py se produção Heroku; documentar em .cursorrules se necessário.
- [ ] Atualizar `docs/SYSTEM.md`: referente do cluster (qualidade mínima / uma substituição); artigo_genesis_id e genesis_trancado se aplicável; find_or_create_cluster não usa embedding para decisão.
- [ ] Antes da Task 6: reler Passo 6 do Guia; localizar classificar_e_resumir_cluster e o uso de ThreadPoolExecutor na Etapa 3 (duas fases opcionais).

---

## Task 6 — Multi-Agent Gating na Etapa 3 (Passo 6 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Ler SYSTEM.md — Etapa 3, classificar_e_resumir_cluster, PROMPT_ANALISE_E_SINTESE_CLUSTER_V1; Gatekeeper V13 (encapsular, não reescrever).
- [ ] Abrir process_articles.py: classificar_e_resumir_cluster (linhas ~843–935); onde o payload é montado (noticias_payload); onde PROMPT_ANALISE_E_SINTESE_CLUSTER_V1 é formatado e chamado; onde está o ThreadPoolExecutor que chama essa função (main, linhas ~669–691).
- [ ] Decidir: implementação mínima (Agente1→Agente2 sequencial dentro de classificar_e_resumir_cluster) ou duas fases (Fase 1 todos Agent1, Fase 2 todos Agent2). Se duas fases: refatorar o bloco da Etapa 3 para duas ondas de submit.

### Implementar

- Implementar conforme **Passo 6** do Guia: PROMPT_AGENTE_MATERIALIDADE_V1; em classificar_e_resumir_cluster chamar Agente 1, parsear JSON, injetar justificativa no prompt do Agente 2 (PROMPT_ANALISE_E_SINTESE_CLUSTER_V1). Opcional: refatorar Etapa 3 em duas fases (Agent1 todos, depois Agent2 todos) para reduzir tempo de parede e rate limit.

### Após implementar

- [ ] Atualizar `docs/SYSTEM.md`: PROMPT_AGENTE_MATERIALIDADE_V1; fluxo de dois agentes na Etapa 3; se duas fases, descrever o novo fluxo.
- [ ] Antes da Task 7: reler Passo 7 do Guia; localizar find_or_create_cluster e processar_artigo_pipeline em backend/processing.py.

---

## Task 7 — Alinhar find_or_create_cluster (API) às mesmas regras (Passo 7 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Ler SYSTEM.md — processing.py find_or_create_cluster, processar_artigo_pipeline; quem chama (main.py background task).
- [ ] Abrir backend/processing.py: find_or_create_cluster (linhas ~302–372); _consultar_llm_para_clusterizacao; onde embedding_medio é atualizado; get_artigos_by_cluster para obter artigos do cluster (gênese).
- [ ] Garantir reuso: extração de fato gerador deve ser função compartilhada (ex. em process_articles ou em processing) para não duplicar lógica entre Etapa 1 e find_or_create_cluster.
- [ ] Verificar normalizar_jornal e FONTES_FLASHES acessíveis a partir de processing.py (import de utils/prompts).

### Implementar

- Implementar conforme **Passo 7** do Guia: em find_or_create_cluster usar fato_gerador (extrair se não existir); comparar com referente de qualidade (gênese); heurística da fonte (mesmo jornal → aviso no prompt; FONTES_FLASHES → prompt mais rigoroso); não atualizar embedding_medio para decisão de anexar.

### Após implementar

- [ ] Atualizar `docs/SYSTEM.md`: find_or_create_cluster alinhado a fato gerador, heurística da fonte e referente gênese.
- [ ] Antes da Task 8: reler Passo 8 do Guia e checklist de documentação/deploy.

---

## Task 8 — Documentação final e deploy (Passo 8 do Guia) ✅ Implementado

### Antes de implementar (pesquisa e impactos)

- [ ] Revisar .cursorrules: REGRA OBRIGATORIA se alterou database.py (migrate_incremental, flags, SQL Heroku); "Manter docs/SYSTEM.md e docs/OPERATIONS.md atualizados".
- [ ] Listar todas as alterações feitas nas Tasks 1–7 e garantir que SYSTEM.md e OPERATIONS.md cobrem novas funções, prompts, tabelas, fluxos e variáveis.

### Implementar

- Atualizar `docs/PROBLEMA_AGRUPAMENTO_NOTICIAS.md`: adicionar seção "Soluções adotadas" com resumo e referência ao Guia e a este documento de task.
- Revisão final de `docs/SYSTEM.md` e `docs/OPERATIONS.md` (completar qualquer lacuna das Tasks anteriores).
- Se houve nova coluna em database.py: confirmar migrate_incremental.py atualizado, flag --include-* e SQL em scripts/migrate_*.py.
- Definir e documentar feature flags (ex.: USE_FATO_GERADOR=1, USE_HEURISTICA_FONTE=1, USE_AGENTE_MATERIALIDADE=1) no código ou em OPERATIONS.md (variáveis de ambiente).

### Após implementar

- [ ] Todas as entradas de "Atualizar SYSTEM.md/OPERATIONS.md" das Tasks 1–7 foram cumpridas.
- [ ] PROBLEMA_AGRUPAMENTO_NOTICIAS.md contém "Soluções adotadas".
- [ ] Feature flags documentadas e, se possível, implementadas para rollout reversível.

---

## Checklist de conformidade com .cursorrules

Ao longo da implementação, verificar:

- [ ] **Leis imutáveis:** Gatekeeper V13 (PROMPT_ANALISE_E_SINTESE_CLUSTER_V1) apenas estendido/contextualizado, não reescrito; nacional e internacional não misturados no mesmo cluster; texto_bruto somente leitura; v2 em shadow mode.
- [ ] **Mudança em database.py:** migrate_incremental.py atualizado; migrate_* idempotente; flag --include-*; SQL para Heroku em scripts/migrate_*.py.
- **Type hints e Pydantic:** novos modelos e funções com tipos; validação via FatoGeradorContract.
- **Erros em LLM:** fallback gracioso (ex.: em falha de extração, sinalizar reprocesso em vez de crash).
- **Arquivos de teste:** deletar após uso (regra "não guardar lixo").
- **Documentação:** SYSTEM.md e OPERATIONS.md atualizados ao implementar features.

---

## Ordem de execução resumida

| Ordem | Task | Guia (Passo) |
|-------|------|--------------|
| 1 | Normalização de jornal + FONTES_FLASHES | Passo 1 |
| 2 | Heurística da fonte na Etapa 2 | Passo 2 |
| 3 | Extração de fato gerador na Etapa 1 | Passo 3 |
| 4 | Etapa 2 usa fato gerador | Passo 4 |
| 5 | Cluster imutável / referente com qualidade | Passo 5 |
| 6 | Multi-Agent Gating na Etapa 3 | Passo 6 |
| 7 | Alinhar find_or_create_cluster (API) | Passo 7 |
| 8 | Documentação final e deploy | Passo 8 |

Sempre: **pesquisar impactos → implementar → atualizar documentação → estudar contexto para a próxima task.**

---

## Resumo do que foi implementado

Todas as 8 tasks foram concluídas. Abaixo, o que foi feito em cada uma e em quais arquivos.

### Task 1 — Normalização de jornal e FONTES_FLASHES ✅

**Arquivos alterados:** `backend/utils.py`, `docs/SYSTEM.md`

**Implementação:**
- **`backend/utils.py`:**
  - Função `normalizar_jornal(nome: Optional[str]) -> str`: lowercase, remoção de acentos (NFKD + combining chars), `re.sub` para separadores; dicionário de aliases (ex.: "o estado de s paulo" → "estadao", "valor pro" → "valor economico").
  - Constante `FONTES_FLASHES: List[str]` com nomes normalizados: valor economico, valor pro, bloomberg, reuters.
- Imports adicionados em `utils.py`: `unicodedata`, `List`.
- **SYSTEM.md:** Registradas `normalizar_jornal` e `FONTES_FLASHES` na tabela de funções essenciais de utils.

---

### Task 2 — Heurística da fonte na Etapa 2 ✅

**Arquivos alterados:** `process_articles.py`, `backend/prompts.py`

**Implementação:**
- **`process_articles.py`:**
  - Em `processar_lote_incremental`: cada item de `novas_noticias` ganhou `"jornal": normalizar_jornal(artigo.jornal) or "N/A"`; cada item de `clusters_existentes_data` ganhou `"jornais_no_cluster": list({normalizar_jornal(a.jornal) for a in artigos_cluster ...})`.
  - Em `agrupar_noticias_com_prompt`: `noticia_data` do lote passou a incluir `"jornal": normalizar_jornal(artigo.jornal) or "N/A"`.
  - Import de `normalizar_jornal` e `FONTES_FLASHES` de `backend.utils`.
  - No `format` do PROMPT_AGRUPAMENTO_INCREMENTAL_V2: `FONTES_FLASHES_LIST=", ".join(FONTES_FLASHES)`.
- **`backend/prompts.py`:**
  - Em **PROMPT_AGRUPAMENTO_INCREMENTAL_V2:** regras 8 e 9: "HEURÍSTICA DA FONTE (MESMO JORNAL)" e "FONTES FLASHES (CRITÉRIO MAIS RIGOROSO)" com placeholder `{FONTES_FLASHES_LIST}`; formato de entrada atualizado (jornal, jornais_no_cluster).
  - Em **PROMPT_AGRUPAMENTO_V1:** nova regra 6 "HEURÍSTICA DA FONTE (MESMO JORNAL)" e renumeração (7 = MAPEAMENTO POR ID).

---

### Task 3 — Extração de fato gerador na Etapa 1 ✅

**Arquivos alterados:** `backend/models.py`, `backend/prompts.py`, `process_articles.py`, `docs/SYSTEM.md`

**Implementação:**
- **`backend/models.py`:** Modelo Pydantic `FatoGeradorContract` com `fato_gerador_padronizado` (obrigatório, max 300), `entidade_primaria`, `verbo_acao_financeira`, `valor_envolvido` (opcionais).
- **`backend/prompts.py`:** Novo `PROMPT_EXTRACAO_FATO_GERADOR_V1` (instruções para JSON: fato_gerador_padronizado, entidade_primaria, verbo_acao_financeira, valor_envolvido).
- **`process_articles.py`:** Em `processar_artigo_sem_cluster`, após validação Noticia (Etapa 3 Pydantic), bloco **Etapa 3.5**: se `metadados` já tem `fato_gerador` válido, reutiliza; senão chama LLM com PROMPT_EXTRACAO_FATO_GERADOR_V1 + título e trecho (2000 chars), faz parse com `extrair_json_da_resposta`, valida com `FatoGeradorContract`; em sucesso grava `metadados['fato_gerador']` e dá `db.commit()`; em falha: se artigo já processado (`titulo_extraido` preenchido) usa fallback título em `metadados['fato_gerador']` e `fato_gerador_fallback=True`; se artigo novo, grava `fato_gerador_erro=True`, `update_artigo_status(..., 'erro')` e retorna False (sem fallback fraco).
- **SYSTEM.md:** Linha sobre Etapa 1 — fato gerador (processar_artigo_sem_cluster, PROMPT_EXTRACAO_FATO_GERADOR_V1, FatoGeradorContract, comportamento em falha).

---

### Task 4 — Etapa 2 usa fato gerador ✅

**Arquivos alterados:** `process_articles.py`, `backend/prompts.py`

**Implementação:**
- **`process_articles.py`:**
  - Em `processar_lote_incremental`: helper `_fato_gerador_artigo(a)` que lê `(a.metadados or {}).get("fato_gerador", {}).get("fato_gerador_padronizado")` ou fallback `titulo_extraido[:120]`; em `novas_noticias` cada item ganhou `"fato_gerador": _fato_gerador_artigo(artigo)`; em `clusters_existentes_data` cada cluster ganhou `"fato_gerador_referente"` (primeiro artigo do cluster, depois refinado na Task 5).
  - Em `agrupar_noticias_com_prompt`: helper `_fg(a)` análogo; `noticia_data` do lote ganhou `"fato_gerador": _fg(artigo)`.
- **`backend/prompts.py`:**
  - PROMPT_AGRUPAMENTO_INCREMENTAL_V2: bloco "DECISÃO POR FATO GERADOR" e formato de entrada com fato_gerador e fato_gerador_referente.
  - PROMPT_AGRUPAMENTO_V1: regra 6 "DECISÃO POR FATO GERADOR".

---

### Task 5 — Cluster imutável / referente com qualidade ✅

**Arquivos alterados:** `process_articles.py`

**Implementação:**
- **`process_articles.py`:** Em `processar_lote_incremental`, ao montar `clusters_existentes_data`: em vez de usar o primeiro artigo do cluster como referente, passou a calcular **referente por qualidade**: `MIN_LEN_REFERENTE = 20`; artigos do cluster ordenados por `created_at`; percorre até achar um com `len(_fato_gerador_artigo(a)) >= 20`; se nenhum, usa o de maior length com `max(..., key=lambda a: len(_fato_gerador_artigo(a)))`. `fato_gerador_referente` do cluster usa esse artigo. Opção A (sem nova coluna) foi usada; não foi alterado `database.py` nem `migrate_incremental.py`.

---

### Task 6 — Multi-Agent Gating na Etapa 3 ✅

**Arquivos alterados:** `backend/prompts.py`, `process_articles.py`, `docs/SYSTEM.md`

**Implementação:**
- **`backend/prompts.py`:** Novo `PROMPT_AGENTE_MATERIALIDADE_V1`: "Advogado do Diabo", pergunta se o evento tem impacto direto e imediato; retorno JSON `deve_ser_p3`, `justificativa_materialidade`.
- **`process_articles.py`:** Em `classificar_e_resumir_cluster`, antes de montar o prompt principal: monta payload curto (até 10 artigos: título, fato_gerador, trecho 400 chars); chama LLM com PROMPT_AGENTE_MATERIALIDADE_V1 (temperature 0.0); parseia JSON; se sucesso, injeta bloco `bloco_materialidade` no início do prompt principal ("TESTE DE MATERIALIDADE (Agente 1)", justificativa, recomendação P3, instrução para só dar P1/P2 com fato quantitativo/gatilho explícito). Fluxo sequencial Agente1 → Agente2 por cluster (não implementadas duas fases em paralelo).
- **SYSTEM.md:** PROMPT_AGENTE_MATERIALIDADE_V1 na tabela de prompts; descrição de `classificar_e_resumir_cluster` atualizada (Agente 1 + classificação/resumo).

---

### Task 7 — Alinhar find_or_create_cluster (API) ✅

**Arquivos alterados:** `backend/processing.py`, `backend/prompts.py`

**Implementação:**
- **`backend/processing.py`:** Imports de `normalizar_jornal` e `FONTES_FLASHES` de utils. Em `processar_artigo_pipeline`, após obter `noticia_validada`: preenche `noticia_validada["fato_gerador"]` a partir de `artigo.metadados["fato_gerador"]["fato_gerador_padronizado"]` ou fallback título[:120]; `noticia_validada["jornal_normalizado"] = normalizar_jornal(...)`. Em `_consultar_llm_para_clusterizacao`: obtém artigos do cluster com `get_artigos_by_cluster`; calcula `jornais_no_cluster` e referente por qualidade (fato_gerador length >= 20) igual à Task 5; monta `nova_noticia` (titulo, jornal, fato_gerador, trecho) e `cluster_info` (titulo_cluster, fato_gerador_referente, jornais_no_cluster, tag); se jornal da notícia está em `jornais_no_cluster`, monta `AVISO_MESMO_JORNAL` (texto mais rigoroso se jornal em FONTES_FLASHES); formata PROMPT_DECISAO_CLUSTER_DETALHADO_V1 com placeholders `NOVA_NOTICIA`, `CLUSTER_EXISTENTE`, `AVISO_MESMO_JORNAL` (em vez dos antigos titulo_artigo, etc.).
- **`backend/prompts.py`:** PROMPT_DECISAO_CLUSTER_DETALHADO_V1 ganhou bloco "DECISÃO POR FATO GERADOR" e placeholder `{AVISO_MESMO_JORNAL}`.

---

### Task 8 — Documentação final e deploy ✅

**Arquivos alterados:** `docs/PROBLEMA_AGRUPAMENTO_NOTICIAS.md`, `docs/SYSTEM.md`

**Implementação:**
- **PROBLEMA_AGRUPAMENTO_NOTICIAS.md:** Adicionada **Parte H — Soluções adotadas (implementação)**: tabela problema × solução × onde atua; nota de schema (fato_gerador em metadados JSON, sem coluna nova); nota de rollout (mudanças ativas; feature flags opcionais).
- **SYSTEM.md:** Já atualizado nas tasks anteriores (normalizar_jornal, FONTES_FLASHES, Etapa 1 fato gerador, PROMPT_EXTRACAO_FATO_GERADOR_V1, PROMPT_AGENTE_MATERIALIDADE_V1, fluxo Etapa 3 com dois agentes). Nenhuma coluna nova; `migrate_incremental.py` não foi alterado. Feature flags não implementadas no código; documentado como opcional (variáveis de ambiente para reverter).

---

### Scripts e fluxo de execução

- **`process_articles.py`:** Suporte a `--day YYYY-MM-DD` no main: repassa `day_str` para `processar_artigos_pendentes`, garantindo que apenas artigos e clusters do dia sejam usados (sem misturar datas). Prints ajustados: escopo por data, resumos em vez de listas de IDs, resumo por lote (anexações, skip tipo_fonte, cluster não encontrado).
- **`run_complete_workflow.py`:** Comentário na etapa 2 explicando que o processamento usa o fluxo novo (fato gerador, heurística fonte, referente qualidade, multi-agent gating). Nenhuma alteração de lógica; o fluxo novo está em `process_articles.py`.
- **`run_test_new_flow.py`:** Criado para testar o novo fluxo: processa até N artigos pendentes do dia; com `--reprocess` reseta N artigos processados do dia e reprocessa; com `--full-day` delega a `reprocess_today.reprocessar_data(day_str)` (reprocessamento completo do dia). Todos usam o mesmo pipeline de `process_articles.py`.
- **`reprocess_today.py`:** Atualizado: docstring e prints deixam explícito que usa o fluxo novo e que processa apenas a data alvo (sem misturar outras datas). Chama `processar_artigos_pendentes(limite=999, day_str=target_day)` e `consolidacao_final_clusters(..., day_str=target_day)` — mesmo fluxo que `run_test_new_flow.py` e `process_articles.py`.
- **`backend/crud.py`:** Print "Cluster já existe" limitado a 50 caracteres do título para evitar poluição de log.

**Conclusão:** `reprocess_today.py` e `run_test_new_flow.py` (com ou sem `--full-day`) rodam o **mesmo fluxo novo** implementado em `process_articles.py` e `backend/processing.py`.
