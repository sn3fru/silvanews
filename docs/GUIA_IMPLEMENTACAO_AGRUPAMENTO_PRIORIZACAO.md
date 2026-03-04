# Guia de Implementação — Agrupamento e Priorização (Propostas 1.A, 2.A, 2.B, 3.A)

Este documento cruza as **propostas de arquitetura** recebidas com os **três problemas** descritos em `docs/PROBLEMA_AGRUPAMENTO_NOTICIAS.md` e com o **código e a documentação** do projeto, para definir as melhores soluções e um **passo a passo de implementação**. O objetivo é implementar **1.A (Extração Fato Gerador) + 2.B (Heurística da Fonte) + 2.A em versão leve (Cluster Imutável para comparação) + 3.A (Multi-Agent Gating)**, com ajustes onde o contexto do AlphaFeed exige. O guia foi **revisado** após análise crítica de edge cases e gargalos de infraestrutura (Seção 7).

---

## 1. Mapeamento: Proposta × Problema × Código Atual

### Problema 1 — Falsos negativos (não agrupar o que deveria)

| Proposta | O que faz | Investigação no código | Veredicto |
|----------|------------|------------------------|-----------|
| **1.A Extração Entidade-Ação** | LLM extrai JSON estrito (entidade_primaria, fato_gerador_padronizado, etc.); agrupamento compara fatos, não textos. | Etapa 1 hoje não usa LLM para extração quando há cache (metadados); quando usa, é extração genérica. Não existe campo `fato_gerador` em `artigos_brutos`. Podemos usar `metadados['fato_gerador']` ou coluna nova. | **Recomendado.** Reduz ruído jornalístico; dá input limpo à Etapa 2. Custo: +1 chamada LLM por artigo na Etapa 1 (ou na transição Etapa 1→2). |
| **1.B Pairwise todos contra todos** | Cada artigo novo vs. cada cluster ativo com prompt binário "mesmo evento? SIM/NÃO". | Pipeline principal (process_articles) já usa só LLM na Etapa 2 (sem embedding para decisão). Fazer N×M perguntas explícitas explodiria chamadas (ex.: 50 artigos × 30 clusters = 1500 chamadas). Rate limit Gemini e latência inviabilizam. | **Não recomendado** para produção. Pode servir como baseline de qualidade em testes A/B com amostra pequena. |

### Problema 2 — Falsos positivos (agrupar o que não deveria)

| Proposta | O que faz | Investigação no código | Veredicto |
|----------|------------|------------------------|-----------|
| **2.A Cluster Imutável (Artigo Gênese)** | Identidade do cluster = primeiro artigo que o originou; comparação sempre contra o "Gênese", não contra resumo/embedding atualizado. | Hoje não existe `artigo_genesis_id` em `clusters_eventos`. `embedding_medio` é atualizado em `find_or_create_cluster` (processing.py) e no merge (crud.py). No script, a Etapa 2 envia `cluster.titulo_cluster` e `titulos_internos` (até 10) — não há conceito de "um único artigo de referência". | **Recomendado em versão leve:** usar um único "referente" por cluster para comparação (título + fato_gerador do gênese), sem atualizar esse referente ao anexar. Reduz "drift" e efeito gravitacional. |
| **2.B Heurística da Fonte** | Se o cluster já tem artigo do **mesmo jornal** que o novo, exige prompt mais restritivo ("só agrupe se for UPDATE/Correção/Consequência imediata") ou bloqueia. | `artigos_brutos.jornal` existe (String 100). Em `processar_lote_incremental` o payload ao LLM **não** inclui `jornal` nas novas notícias nem lista de jornais por cluster; só `id` e `titulo`. Precisamos: (1) normalizar jornal (Estadão/estadao/O Estado de S. Paulo → mesma chave); (2) enviar jornal por notícia e por cluster; (3) regra no prompt ou em código. **Correção pós-análise:** A restrição aplica-se a **todas** as fontes. Para FONTES_FLASHES (Valor Pro, etc.) o que muda é o **texto do prompt** (mais rigoroso: "só agrupe se Entidade e Ação forem exatamente continuação do fato anterior"), não a isenção da regra. | **Recomendado.** Implementação barata; alinhado à pista do documento de problemas. |

### Problema 3 — Priorização mal feita (excesso de P1/P2)

| Proposta | O que faz | Investigação no código | Veredicto |
|----------|------------|------------------------|-----------|
| **3.A Multi-Agent Gating** | Agente 1 (Advogado do Diabo): "Por que isso seria P3? Que impacto direto hoje?"; Agente 2 (Classificador) recebe a justificativa e classifica. Premissa padrão = rejeição (P3). | Etapa 3 é uma única chamada em `classificar_e_resumir_cluster` (process_articles.py) com `PROMPT_ANALISE_E_SINTESE_CLUSTER_V1`, que já contém regras de rejeição e P1/P2/P3. O prompt faz análise + resumo + prioridade de uma vez ("diluição de atenção"). | **Recomendado.** Separar em duas chamadas: (1) só "teste de materialidade" (output: justificativa + sugestão P3 ou candidato P1/P2); (2) classificação final + resumo usando essa justificativa. Aumenta latência/custo da Etapa 3 (~1,5x), mas alinha com "default P3". |
| **3.B Few-Shot RAG de priorização** | Banco vetorial de exemplos P1/P2 validados por humanos; classificador busca 3 exemplos mais próximos e aplica mesma prioridade. | Não existe hoje dataset "gold" de notícias P1/P2 curado. Feedback (likes/dislikes) existe em `feedback_noticias` e é usado em `get_feedback_rules()` para regras textuais, não para retrieval por similaridade. | **Opcional/fase 2.** Requer curadoria contínua. Pode ser adicionado depois como camada de refinamento sobre 3.A. |

---

## 2. Decisões de desenho (ajustes ao contexto AlphaFeed)

- **1.A:** Armazenar fato gerador em **`metadados['fato_gerador']`** (evita migration de coluna no primeiro momento). **Contrato validado por Pydantic** (`FatoGeradorContract`): `fato_gerador_padronizado` (max 15 palavras), opcionalmente `entidade_primaria`, `verbo_acao_financeira`, `valor_envolvido`. Se a extração falhar, não usar fallback fraco (titulo[:80]); sinalizar artigo para reprocessamento. Opcionalmente depois migrar para coluna dedicada se quisermos indexar/filtrar.
- **2.B:** Normalização de jornal: criar `normalizar_jornal(nome)` (lowercase, acentos, aliases). A restrição "mesmo jornal → só agrupe se update/consequência" aplica-se a **todas** as fontes. Para **FONTES_FLASHES** (Valor Pro, terminais de tempo real): usar prompt **mais rigoroso**, não isenção — ex.: "Esta fonte emite atualizações fragmentadas. Seja extremamente rigoroso: só agrupe se a Entidade e a Ação Financeira forem exatamente uma continuação do fato anterior."
- **2.A (leve):** O referente do cluster não pode ser cegamente o "primeiro artigo cronológico": em crises, o primeiro a sair é muitas vezes um flash de uma linha (ex.: "URGENTE: Empresa X entra com pedido de RJ"), gerando fato_gerador pobre e aumentando falsos negativos quando artigos mais completos chegam depois. **Regra:** O referente (gênese) deve ter **qualidade mínima**: ex. `fato_gerador_padronizado` com pelo menos N caracteres (ex.: 20) ou permitir **uma única substituição** do referente pelo segundo artigo mais completo antes de trancar. Opcional: coluna `artigo_genesis_id`; ao criar cluster, definir gênese só quando um artigo atingir o limiar de qualidade (ou trancar após a primeira substituição).
- **3.A:** Primeira chamada (Agente Advogado do Diabo): prompt curto, temperatura baixa (0.0–0.1), saída estruturada: `{ "deve_ser_p3": true|false, "justificativa_materialidade": "..." }`. Segunda chamada: prompt atual de classificação + resumo, com novo bloco de contexto: "Justificativa de materialidade (Agente 1): {justificativa}. Se deve_ser_p3 era true, prefira P3 a menos que haja fato quantitativo/gatilho claro para P1/P2."

---

## 3. Ordem de implementação sugerida

A ordem respeita dependências: schema e dados que a Etapa 2 e 3 consomem vêm primeiro; depois regras de agrupamento; por último priorização.

1. **Fase 1 — Base para Fato Gerador e Fonte**
   - 1.1 Normalização de jornal + heurística da fonte (2.B) — sem LLM novo.
   - 1.2 Extração de fato gerador (1.A) na Etapa 1 e armazenamento em `metadados`.
   - 1.3 (Opcional) Coluna `artigo_genesis_id` em clusters e uso na comparação (2.A leve).

2. **Fase 2 — Agrupamento**
   - 2.1 Etapa 2 (incremental e lote) passa a usar `fato_gerador_padronizado` (+ título) para comparação, não texto completo.
   - 2.2 Cluster "imutável para comparação": referente do cluster = gênese (ou primeiro artigo) em `clusters_existentes_data`.

3. **Fase 3 — Priorização**
   - 3.1 Multi-Agent Gating (3.A) na Etapa 3: Agente 1 (materialidade) → Agente 2 (classificação + resumo).

4. **Fase 4 — Caminho API (processar_artigo_pipeline)**
   - 4.1 Alinhar `find_or_create_cluster` com as mesmas regras: uso de fato_gerador, heurística da fonte, comparação com gênese quando existir.

---

## 4. Passo a passo de implementação

### Passo 1 — Normalização de jornal e lista de fontes "flashes"

**Objetivo:** Permitir heurística "mesmo jornal" de forma confiável. A restrição aplica-se a **todas** as fontes; para flashes o que muda é o **rigor do prompt**, não a isenção.

**Arquivos:**
- `backend/utils.py`: adicionar `normalizar_jornal(nome: str) -> str` (lower, unidecode ou remoção de acentos, strip; mapear aliases conhecidos para chave canônica).
- `backend/prompts.py` ou config: constante `FONTES_FLASHES` (lista de nomes normalizados que emitem updates fragmentados, ex.: `["valor economico", "valor pro"]`).

**Lógica:**
- `normalizar_jornal("O ESTADO DE S. PAULO")` → `"estadao"`; `"Valor Econômico"` → `"valor economico"`.
- **Não** isentar FONTES_FLASHES da regra "mesmo jornal". Para fontes em FONTES_FLASHES, usar um **prompt mais rigoroso**: "Esta fonte emite atualizações fragmentadas a cada minuto. Seja extremamente rigoroso: só agrupe se a Entidade e a Ação Financeira forem exatamente uma continuação do fato anterior." Assim evitamos que terminais de tempo real poluam clusters com ruído setorial (várias notas sobre fatos diferentes no mesmo setor).

**Testes:** Unit test para `normalizar_jornal` com vários inputs (Estadão, Valor, Brazil Journal, etc.).

---

### Passo 2 — Heurística da fonte na Etapa 2 (2.B)

**Objetivo:** Quando o cluster já tem artigo(s) do **mesmo jornal** (normalizado) que a nova notícia, o LLM recebe aviso e instrução de só agrupar se for update/correção/consequência imediata; ou podemos em código não propor esse cluster como candidato (mais restritivo).

**Arquivos:**
- `process_articles.py`: em `processar_lote_incremental`, ao montar `novas_noticias`, incluir `"jornal": normalizar_jornal(artigo.jornal or "")`. Ao montar `clusters_existentes_data`, incluir `"jornais_no_cluster": list(set(normalizar_jornal(a.jornal or "") for a in artigos_cluster))`.
- `backend/prompts.py`: em `PROMPT_AGRUPAMENTO_INCREMENTAL_V2`, adicionar bloco condicional (ou sempre presente): "Para cada cluster, o campo `jornais_no_cluster` lista as fontes já presentes. Se a nova notícia tiver `jornal` igual a um dos `jornais_no_cluster`, só anexe se for claramente um UPDATE, CORREÇÃO ou CONSEQUÊNCIA IMEDIATA do mesmo fato. Caso contrário, crie NOVO CLUSTER."
- Opcional: em código, antes de enviar ao LLM, marcar candidatos "mesmo_jornal" e injetar no prompt por cluster "CUIDADO: esta notícia é do mesmo jornal que já está no cluster X."

**FONTES_FLASHES:** Se o jornal estiver em FONTES_FLASHES, injetar o aviso **mais rigoroso** (Entidade + Ação como continuação exata do fato anterior), não um aviso mais suave. A restrição continua a aplicar-se.

**Testes:** Rodar um lote com 2 notícias do mesmo jornal sobre fatos diferentes e verificar que não são agrupadas (ou que o LLM recebe o aviso).

---

### Passo 3 — Extração de fato gerador na Etapa 1 (1.A)

**Objetivo:** Todo artigo processado na Etapa 1 passa por uma chamada LLM que extrai um "contrato de dados"; o resultado é validado e salvo em `metadados['fato_gerador']` para uso na Etapa 2. **Evitar assimetria de dados:** comparar no LLM um fato_gerador estruturado com um título truncado (fallback fraco) aumenta alucinação e rejeição.

**Arquivos:**
- `backend/models.py` (ou novo módulo de contratos): criar modelo **Pydantic** `FatoGeradorContract` com campos obrigatórios, ex.: `fato_gerador_padronizado: str` (max 15 palavras), opcionalmente `entidade_primaria`, `verbo_acao_financeira`, `valor_envolvido`. Validar todo output da extração com este modelo.
- `backend/prompts.py`: novo prompt `PROMPT_EXTRACAO_FATO_GERADOR_V1` com instruções para retornar JSON compatível com `FatoGeradorContract`. Temperature 0.0 ou 0.1.
- `process_articles.py`: em `processar_artigo_sem_cluster`, após obter `noticia_data`, chamar LLM; parsear JSON e validar com `FatoGeradorContract`. Se **validação falhar ou LLM falhar**: **não** usar fallback `titulo[:80]`; marcar artigo para reprocessamento (ex.: manter status `pronto_agrupar` mas com flag `metadados.fato_gerador_erro = true` ou status temporário que impeça de entrar na Etapa 2 até reprocesso; ou `update_artigo_status(db, id_artigo, 'erro')` e log para retry). Só gravar em `metadados['fato_gerador']` quando o contrato for válido.
- Para **artigos já existentes** (backfill): pode-se permitir fallback temporário (título) apenas para os que já estão no banco sem `fato_gerador`, até rodar um job de backfill; para **novos** artigos, regra estrita.

**Testes:** Processar um artigo e inspecionar `metadados['fato_gerador']`; forçar falha de extração e verificar que o artigo não avança para Etapa 2 com dado fraco.

---

### Passo 4 — Etapa 2 usa fato gerador para comparação (1.A concluído)

**Objetivo:** Na Etapa 2 (incremental e lote), o LLM recebe **fato_gerador_padronizado** (e título) das notícias e dos clusters, não o texto completo.

**Arquivos:**
- `process_articles.py` — `processar_lote_incremental`: em `novas_noticias`, incluir `"fato_gerador": (artigo.metadados or {}).get("fato_gerador", {}).get("fato_gerador_padronizado") or artigo.titulo_extraido or "Sem título"`. Em `clusters_existentes_data`, para cada cluster usar o **primeiro artigo** (ou artigo gênese quando existir) para obter o fato gerador de referência: `fato_gerador_referente = (primeiro_artigo.metadados or {}).get("fato_gerador", {}).get("fato_gerador_padronizado") or cluster.titulo_cluster`. Enviar no payload `tema_principal` ou `fato_gerador_referente` e, por cluster, `titulos_internos` podem ser mantidos para contexto, mas a "âncora" de comparação é o fato gerador.
- `backend/prompts.py`: em `PROMPT_AGRUPAMENTO_INCREMENTAL_V2` e em `PROMPT_AGRUPAMENTO_V1`, deixar explícito que a decisão de "mesmo evento" deve ser baseada no **fato gerador** (e no aviso de mesmo jornal já inserido no passo 2).

**Compatibilidade:** Artigos já existentes (antes do backfill) podem usar fallback para título na Etapa 2 até que um job de backfill preencha `fato_gerador`. Para **novos** artigos (processados após a implementação), só avançar para Etapa 2 com `fato_gerador` válido (contrato Pydantic); caso contrário, sinalizar erro e reprocessar (ver Passo 3).

---

### Passo 5 — Cluster imutável para comparação (2.A leve)

**Objetivo:** A "identidade" do cluster para fins de comparação não muda ao anexar novos artigos; o referente deve ter **qualidade mínima** para não virar âncora fraca (falsos negativos).

**Risco do "primeiro cronológico":** Em crises, o primeiro artigo a sair costuma ser um flash de uma linha (ex.: "URGENTE: Empresa X entra com pedido de RJ"). Se esse for o gênese, o fato_gerador extraído será pobre; quando artigos mais completos chegarem depois, a comparação contra um gênese anêmico aumenta rejeições (falsos negativos).

**Regra de qualidade do referente:**
- O referente (gênese) só é **trancado** quando o `fato_gerador_padronizado` do artigo tiver tamanho mínimo (ex.: ≥ 20 caracteres) ou quando já tiver ocorrido **uma única substituição**. Ex.: ao criar cluster, se o primeiro artigo tiver fato_gerador com &lt; 20 chars, não trancar ainda; ao anexar o segundo, se o segundo tiver fato_gerador mais completo (ex.: ≥ 20 chars), promover o segundo a gênese **uma vez** e trancar a partir daí.
- Implementação: em memória ou em coluna `artigo_genesis_id` + flag `genesis_trancado` (ou lógica: "gênese = primeiro artigo do cluster com fato_gerador de tamanho ≥ N; se nenhum tiver, usar o de maior tamanho; após primeiro artigo anexado que tenha tamanho ≥ N, trancar gênese").

**Opção A — Sem schema novo:** Ao montar `clusters_existentes_data`, calcular o referente por qualidade: entre os artigos do cluster (ordem por `created_at`), escolher o que tiver `fato_gerador_padronizado` com length ≥ limiar (ex.: 20); se nenhum atingir, usar o de maior length. Não usar `cluster.titulo_cluster`/resumo para comparação.

**Opção B — Com schema:** `artigo_genesis_id` em `ClusterEvento`; ao criar cluster, definir genesis = artigo criador; ao anexar o primeiro artigo que tenha fato_gerador com length ≥ N e o gênese atual tiver menos de N caracteres, permitir **uma única** atualização de `artigo_genesis_id` para esse artigo e trancar (ex.: coluna `genesis_trancado: bool` ou simplesmente não voltar a atualizar).

**Caminho API (processing.py):** Idem: comparar sempre com o referente de qualidade (gênese); não atualizar `embedding_medio` para decisão de anexar.

**Testes:** Criar cluster com um flash curto; anexar artigo completo sobre o mesmo fato; verificar que o referente usado na próxima comparação é o mais completo (ou o trancado após uma substituição). Terceiro artigo (mesmo fato) deve ser comparado ao referente forte, não ao flash.

---

### Passo 6 — Multi-Agent Gating na Etapa 3 (3.A)

**Objetivo:** Antes de classificar e resumir, um "Agente 1" avalia materialidade; o resultado é passado ao classificador com default P3.

**Arquivos:**
- `backend/prompts.py`: novo `PROMPT_AGENTE_MATERIALIDADE_V1`: "Dado o conjunto de notícias abaixo, responda: (1) Este evento tem impacto direto e imediato na estruturação financeira, liquidez ou status jurídico de empresas/mercado hoje? (2) Se não, por que seria no máximo P3 (monitoramento)? Retorne JSON: {\"deve_ser_p3\": true|false, \"justificativa_materialidade\": \"...\"}." Temperature 0.0 ou 0.1.
- `process_articles.py`: em `classificar_e_resumir_cluster`, antes da chamada atual ao PROMPT_ANALISE_E_SINTESE_CLUSTER_V1: (1) montar payload curto (títulos + primeiros 500 chars de cada artigo, ou só fato_gerador dos artigos); (2) chamar LLM com PROMPT_AGENTE_MATERIALIDADE_V1; (3) parsear JSON; (4) na chamada principal, injetar no prompt: "--- TESTE DE MATERIALIDADE (Agente 1) ---\nJustificativa: {justificativa_materialidade}\nRecomendação: preferir P3 = {deve_ser_p3}\n---\nCom base nisso, classifique prioridade e elabore o resumo. Se deve_ser_p3 for true, só atribua P1 ou P2 se houver fato quantitativo ou gatilho explícito (valor, decisão vinculante, default, etc.)."

**Custo:** +1 chamada LLM por cluster na Etapa 3. Latência sobe (~1,5x na etapa).

**Execução e gargalo de infraestrutura:** A Etapa 3 hoje já roda com `ThreadPoolExecutor` (vários clusters em paralelo, ex.: max_workers=8). Dentro de cada worker, Agente 1 e Agente 2 seriam sequenciais (Agent2 depende do output de Agent1). Em dias com muitos clusters (ex.: 40), o tempo total da etapa pode ficar alto e aumentar risco de rate limit da API Gemini. **Diretiva técnica:** (1) **Opção mínima:** manter Agente1→Agente2 sequencial por cluster dentro de cada worker (comportamento atual do pool); monitorar tempo e rate limit. (2) **Opção recomendada para produção:** refatorar em **duas fases** — **Fase 1:** executar Agente 1 (materialidade) para **todos** os clusters em paralelo (ex.: mesmo ThreadPoolExecutor, task = só Agent1); **Fase 2:** com os resultados em mão, executar Agente 2 (classificação + resumo) para todos os clusters em paralelo. Assim evita-se duplicar o tempo de parede da etapa e distribui-se melhor as chamadas à API. Implementar com `concurrent.futures` ou, se o pipeline migrar para async, `asyncio.gather` em duas ondas.

**Testes:** Rodar Etapa 3 em clusters conhecidos (ex.: um de macro genérico, um de RJ) e verificar que o primeiro tende a P3 e o segundo a P1/P2.

---

### Passo 7 — Alinhar find_or_create_cluster (API) às mesmas regras

**Objetivo:** O processamento via API (`processar_artigo_pipeline` → `find_or_create_cluster`) deve usar fato gerador, heurística da fonte e referente gênese.

**Arquivos:**
- `backend/processing.py`: Em `find_or_create_cluster`: (1) Se o artigo ainda não tiver `metadados.fato_gerador`, chamar a mesma extração de fato gerador (ou reutilizar função de process_articles) antes de comparar. (2) Ao iterar clusters ativos, para cada cluster obter o artigo gênese (ou primeiro); comparar usando fato_gerador e título do gênese no prompt, não titulo_cluster/resumo_cluster. (3) Antes de chamar o LLM de decisão, checar heurística da fonte: se o cluster já tem artigo do mesmo jornal (normalizado) e o jornal não está em FONTES_FLASHES, injetar no prompt o aviso "mesmo jornal — só agrupe se for update/consequência". (4) Opcional: não atualizar `embedding_medio` ao anexar (ou manter apenas para uso na Etapa 4), para evitar drift.

**Testes:** Via API, processar um artigo e verificar que foi anexado ou não conforme fato gerador e regra de mesmo jornal.

---

### Passo 8 — Documentação e deploy

- Atualizar `docs/PROBLEMA_AGRUPAMENTO_NOTICIAS.md` com "Soluções adotadas" e referência a este guia.
- Atualizar `docs/SYSTEM.md` com: novo prompt PROMPT_EXTRACAO_FATO_GERADOR_V1, PROMPT_AGENTE_MATERIALIDADE_V1, fluxo de dois agentes na Etapa 3, campo `artigo_genesis_id` e `metadados.fato_gerador`, normalização de jornal e FONTES_FLASHES.
- Se houver nova coluna: seguir regra de `.cursorrules` (migrate_incremental, flags --include-*, SQL para Heroku em scripts/migrate_*.py).
- Rollout: habilitar por feature flag (ex.: `USE_FATO_GERADOR=1`, `USE_HEURISTICA_FONTE=1`, `USE_AGENTE_MATERIALIDADE=1`) para poder reverter sem deploy.

---

## 5. Resumo das soluções escolhidas e onde atuam

| Problema | Solução | Onde atua no código |
|----------|---------|----------------------|
| 1 — Falsos negativos | 1.A Extração de fato gerador; Etapa 2 compara por fato_gerador | processar_artigo_sem_cluster (nova chamada LLM + metadados); processar_lote_incremental e agrupar_noticias_com_prompt (payload com fato_gerador); find_or_create_cluster |
| 2 — Falsos positivos | 2.B Heurística da fonte + 2.A Cluster imutável (referente = gênese) | processar_lote_incremental (jornais_no_cluster, aviso no prompt); clusters_existentes_data com referente do gênese; find_or_create_cluster (não atualizar embedding para decisão; comparar com gênese) |
| 3 — Priorização | 3.A Multi-Agent Gating (Agente 1  materialidade → Agente 2 classificação) | classificar_e_resumir_cluster (duas chamadas LLM; injeção de justificativa no prompt principal) |

---

## 6. Riscos e mitigações

- **Alucinação no fato gerador (1.A):** Temperature 0.0–0.1; prompt com exemplos; **contrato Pydantic** e sem fallback fraco (titulo[:80]) para novos artigos — em caso de falha, reprocessar.
- **Excesso de novos clusters por 2.B:** Se a normalização de jornal for muito agressiva, jornais diferentes podem ser considerados iguais (ou o contrário). Mitigação: mapear manualmente aliases críticos (Estadão, Valor, etc.) e testar com amostras reais.
- **P3 em excesso (3.A):** Se o Agente 1 for muito conservador, eventos relevantes podem ser rebaixados. Mitigação: no prompt do Agente 2, deixar explícito "se há valor em R$, decisão judicial vinculante, ou default anunciado, pode ser P1/P2 mesmo que o Agente 1 tenha sugerido P3".
- **Latência/custo e rate limit (3.A):** Aumento de chamadas na Etapa 3. Mitigação: executar em **duas fases** (Agente 1 para todos em paralelo, depois Agente 2 para todos em paralelo) para não duplicar o tempo de parede e distribuir chamadas à API.
- **Gênese fraco (2.A):** Primeiro artigo do dia pode ser flash de uma linha. Mitigação: referente com qualidade mínima (ex.: fato_gerador com ≥ 20 chars) ou uma única substituição antes de trancar.

---

## 7. Revisão crítica (edge cases e correções incorporadas)

Uma análise externa do guia apontou falhas lógicas em casos de fronteira e gargalos de infraestrutura. As correções abaixo foram incorporadas ao texto.

| Crítica | Ajuste feito no guia |
|--------|----------------------|
| **Gênese cronológico fraco** | O "primeiro artigo" pode ser um flash de uma linha, gerando fato_gerador pobre e falsos negativos. **Correção:** Referente do cluster só é trancado quando o fato_gerador tiver qualidade mínima (ex.: ≥ 20 caracteres) ou após **uma única substituição** pelo segundo artigo mais completo (Passo 5 e decisões 2.A). |
| **Brecha FONTES_FLASHES** | Isentar fontes "flashes" da regra do mesmo jornal anula a defesa contra falsos positivos (várias notas sobre fatos diferentes no mesmo setor). **Correção:** A restrição aplica-se a **todas** as fontes. Para FONTES_FLASHES o que muda é o **prompt** (mais rigoroso: "só agrupe se Entidade e Ação forem exatamente continuação do fato anterior"), não a isenção (Passo 1 e 2, decisão 2.B). |
| **Assimetria de dados / fallback fraco** | Comparar no LLM um fato_gerador estruturado com título truncado (fallback) aumenta alucinação e rejeição. **Correção:** Contrato **Pydantic** `FatoGeradorContract`; se a extração falhar, **não** avançar o artigo para a Etapa 2 com dado fraco — sinalizar para reprocessamento. Fallback (título) apenas para artigos já existentes até backfill (Passo 3). |
| **Gargalo síncrono na Etapa 3** | Duas chamadas sequenciais por cluster dentro do loop podem causar timeouts e rate limit em dias com muitos clusters. **Correção:** Diretiva técnica no Passo 6: refatorar para **duas fases** — Fase 1 executar Agente 1 para todos os clusters em paralelo; Fase 2 executar Agente 2 para todos com os resultados. O código atual já usa `ThreadPoolExecutor` por cluster; a opção em duas fases evita duplicar o tempo de parede e distribui melhor as chamadas à API. |

Com este guia, a implementação pode ser feita por etapas, com cada passo verificável no código e na documentação existente (SYSTEM.md, OPERATIONS.md, PROBLEMA_AGRUPAMENTO_NOTICIAS.md).