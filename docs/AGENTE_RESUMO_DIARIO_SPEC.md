# Especificação: Agente de Resumo Diário (Special Situations → WhatsApp)

> **Status:** Implementado (v3.0 Multi-Tenant)  
> **Objetivo:** Agente que produz um resumo do dia com as principais notícias e oportunidades para a mesa de Special Situations, consumindo **todos os sourcers** (Brasil Físico, Brasil Online, Internacional), com saída para **WhatsApp**.  
> **Data:** 2026-03-06 | **Atualizado:** 2026-03-15

---

## Índice

1. [Visão Geral e Objetivos](#1-visão-geral-e-objetivos)
2. [Fontes de Dados (Sourcers)](#2-fontes-de-dados-sourcers)
3. [Arquitetura: Injeção de Contexto Map-Reduce e Tools](#3-arquitetura-injeção-de-contexto-map-reduce-e-tools)
4. [Tools do Agente (READ-ONLY)](#4-tools-do-agente-read-only)
5. [Cache de Contexto Compartilhado](#5-cache-de-contexto-compartilhado)
6. [Personalização Por Usuário (v3.0)](#6-personalização-por-usuário-v30)
7. [Fluxo Single-Shot e Limite de Tools](#7-fluxo-single-shot-e-limite-de-tools)
8. [Seleção e Curadoria (Thresholding de Qualidade)](#8-seleção-e-curadoria-thresholding-de-qualidade)
9. [Formato de Saída e Entrega (WhatsApp)](#9-formato-de-saída-e-entrega-whatsapp)
10. [Relação com Componentes Existentes](#10-relação-com-componentes-existentes)
11. [Onde Está Implementado](#11-onde-está-implementado)
12. [Requisitos de Infra e Config](#12-requisitos-de-infra-e-config)
13. [Contrato Pydantic (v3.0)](#13-contrato-pydantic-v30)
14. [Decisões e Riscos](#14-decisões-e-riscos)
15. [Referência Técnica e Histórico de Versões](#15-referência-técnica-e-histórico-de-versões)

---

## 1. Visão Geral e Objetivos

### 1.1 O que o agente faz

- **Entrada:** Clusters do dia já processados (status ativo, prioridade e tag definidos) em **todas as fontes**: Brasil Físico, Brasil Online e Internacional.
- **Processo:** O **script em Python** faz uma **pré-query** e injeta no prompt inicial um bloco de contexto (títulos + resumos para P1/P2/P3; para P3 o resumo é curto, 1 frase). O agente opera em **fluxo single-shot**: lê o contexto, pode chamar tools **read-only** (`obter_textos_brutos_cluster`, `buscar_na_web`) conforme budget, e **devolve** o JSON final. O agente **seleciona** até 12 oportunidades por **thresholding de qualidade** (sem mínimo fixo). Sem loops de planeamento ou checagem estéreis.
- **Saída:** Um **resumo do dia** (TL;DR executivo opcional + clusters selecionados com título/bullet/fonte), formatado para envio via **WhatsApp**. O agente **nunca** altera o banco (sem split/merge).

### 1.2 Dois modos de operação

| Modo | Função | Descrição |
|------|--------|-----------|
| **Unificado (padrão)** | `gerar_resumo_diario(date)` | **1 chamada LLM** que cobre todos os ângulos (distressed, regulatório, estratégico, geral). O LLM recebe todos os títulos+resumos do dia e decide onde aprofundar com tools. Custo: 1 chamada + até 5 tool calls. |
| **Per-User (v3.0)** | `gerar_resumo_para_usuario(user_id, date)` | Lê preferências do usuário no banco, monta prompt personalizado com o contexto compartilhado, faz **1 chamada LLM**. Custo: 1 chamada por usuário + até 8 tool calls. |

**Modo Unificado (padrão — terminal/WhatsApp):**
- Contexto montado **UMA VEZ** via `_build_context_block()`.
- **1 chamada LLM** com `PROMPT_RESUMO_UNIFICADO_V1` (cobre distressed + regulatório + estratégico + geral).
- O LLM marca cada cluster com `secao` ("distressed", "regulatorio", "estrategico", "geral").
- Tools disponíveis com budget de 5 chamadas — o LLM decide onde aprofundar.
- Formatador agrupa por seção automaticamente.

**Per-User (v3.0):**
- Contexto compartilhado com **cache** (chave: `date + max(updated_at)`).
- Uma chamada LLM por usuário com preferências personalizadas.
- Custo: 1x tokens/usuário.
- Ideal para escala (100+ usuários).

### 1.3 Princípios

| Princípio | Descrição |
|-----------|-----------|
| **READ-ONLY** | O agente **não** invoca operações de mutação (split/merge). Curadoria do WhatsApp não é o momento de corrigir clustering. |
| **Injeção Map-Reduce** | Contexto inicial é montado em Python: todos os títulos + resumos de P1/P2/P3 (P3 com resumo curto de 1 frase). Uma única injeção; evita dezenas de chamadas e reduz latência/custo. |
| **Single-shot com tools opcionais** | O agente recebe o contexto total do dia numa única injeção. Pode chamar `obter_textos_brutos_cluster` e `buscar_na_web` conforme budget. Sumarização é síntese direta, não exploração profunda. |
| **Saída estruturada (Pydantic)** | O LLM não devolve texto solto; devolve um JSON que o script valida com Pydantic e depois formata para WhatsApp. |
| **Multi-sourcer** | Sempre considerar os três tipos de fonte: `brasil_fisico`, `brasil_online`, `internacional`. |

---

## 2. Fontes de Dados (Sourcers)

### 2.1 Tipos de fonte no sistema

O AlphaFeed já distingue três tipos de fonte (além do legado `nacional`):

| `tipo_fonte` | Descrição | Exemplos |
|--------------|-----------|----------|
| `brasil_fisico` | Jornais em PDF (imprensa física) | Valor, Estadao, etc. |
| `brasil_online` | Fontes online brasileiras | Sites, crawlers, JSONs com URL |
| `internacional` | Fontes internacionais | Bloomberg, Reuters, etc. |

- **CRUD:** `list_sourcers_by_date_and_tipo(db, target_date, tipo_fonte)` retorna lista de sourcers com contagem.
- **Feed/Clusters:** `get_clusters_for_feed_by_date(..., tipo_fonte=...)` aceita `brasil_fisico`, `brasil_online`, `internacional` ou `nacional` (agrupa fisico+online).
- **Artigos raw por fonte:** `list_raw_articles_by_source_date_tipo(db, source, target_date, tipo_fonte)`.

**Regra de ouro (já existente):** Nacional e Internacional **nunca** se misturam no mesmo cluster (`tipo_fonte` em `artigos_brutos` e `clusters_eventos`).

### 2.2 O que o agente consume

- Clusters **ativos** do dia com `tipo_fonte` em `brasil_fisico`, `brasil_online`, `internacional`.
- `_build_context_block()` lê todos os clusters do dia de uma vez e monta o bloco de texto estruturado.

---

## 3. Arquitetura: Injeção de Contexto Map-Reduce e Tools

O **script em Python** faz uma **pré-query** e injeta um único bloco de contexto no prompt inicial:

```
PRÉ-QUERY (em Python, executada UMA VEZ via _build_context_block):
  - Recolher TODOS os clusters do dia (P1, P2 e P3), todas as fontes.
  - Para P1 e P2: injetar titulo_cluster, resumo_cluster (longo/médio), prioridade, tag, tipo_fonte, id, total_artigos.
  - Para P3: injetar id, titulo_cluster, resumo_cluster (curto, 1 frase), prioridade, tag, tipo_fonte.
  → Montar um único bloco de texto estruturado e enviar no prompt inicial.
```

Assim o agente já "vê" o dia numa única injeção. As tools disponíveis são:

- **`obter_textos_brutos_cluster(cluster_id)`** — para dúvidas factuais (valores, nomes, datas). Hard-limit de **3000 caracteres** por artigo.
- **`buscar_na_web(query)`** — busca Tivaly para complementar com dados atualizados. Requer `TIVALY_API_KEY`; máximo **2 chamadas por sessão**.

---

## 4. Tools do Agente (READ-ONLY)

Todas as tools são **somente leitura**. Nenhuma tool de split ou merge é exposta a este agente.

### 4.1 Obter textos brutos de um cluster

| Item | Descrição |
|------|-----------|
| **Nome** | `obter_textos_brutos_cluster` |
| **Objetivo** | Retornar textos dos artigos do cluster para **dúvidas factuais rápidas** (qual o valor da multa? nome da filial?). |
| **Parâmetros** | `cluster_id` (int). |
| **Retorno** | Lista de `{ id, titulo, fonte, texto_bruto }`. |
| **Limite** | **3000 caracteres** por artigo (`texto_bruto` truncado). |
| **Backend** | `get_textos_brutos_por_cluster_id(db, cluster_id)` com pós-processamento. |

O contexto inicial (títulos + resumos P1/P2/P3) é **injetado pelo script** no prompt; a tool serve só para complemento pontual.

### 4.2 Buscar na web (Tivaly)

| Item | Descrição |
|------|-----------|
| **Nome** | `buscar_na_web` |
| **Objetivo** | Busca na web em tempo real para complementar contexto (cotações, decisões recentes, notícias de última hora). |
| **Parâmetros** | `query` (string). |
| **Retorno** | `{ status, results: [{ title, snippet, url }] }` — até 3 resultados. |
| **Config** | `TIVALY_API_KEY` obrigatória. Sem a chave, retorna `status: "unavailable"`. |
| **Limite** | Máximo **2 chamadas por sessão** (evita custo excessivo). |

---

## 5. Cache de Contexto Compartilhado

### 5.1 Construção do contexto

- **`_build_context_block(db, target_date)`** lê **todos** os clusters do dia **UMA VEZ**.
- Paginação via `get_clusters_for_feed_by_date` até esgotar.
- Para cada cluster: P1/P2 com resumo completo; P3 com resumo truncado (1 frase).
- Inclui estatísticas de temperatura e regras de curadoria adaptativa.

### 5.2 Chave de cache

| Chave | Formato | Invalidação |
|-------|---------|-------------|
| Cache key | `{date}_{max(updated_at)}` | Quando novos PDFs chegam e clusters são atualizados (`updated_at` muda). |

- `max(updated_at)` é calculado sobre `clusters_eventos` do dia.
- Cache invalidado automaticamente: ao mudar dados dos clusters, nova chave gera novo contexto.
- Cache anterior é limpo (`_CONTEXT_CACHE.clear()`) antes de gravar novo valor.

### 5.3 Temperatura do dia

| Temperatura | Condição | Regra de curadoria |
|-------------|----------|---------------------|
| **QUENTE** | P1+P2 ≥ 5 **e** tags distintas ≥ 3 | Seja RIGOROSO. 7–12 itens mais impactantes. |
| **MORNO** | P1+P2 ≥ 2 | Priorize P1+P2, complemente com melhores P3. 5–8 itens. |
| **FRIO** | Caso contrário | Baixe a régua. 3–5 itens (melhores P3). |

As regras de curadoria adaptativa são **injetadas no contexto** como texto (header do bloco).

---

## 6. Personalização Por Usuário (v3.0)

### 6.1 Fonte de preferências

| Tabela/Campo | Uso |
|--------------|-----|
| `preferencias_usuario.tags_interesse` | Tags de foco — priorizar clusters com essas tags. |
| `preferencias_usuario.tags_ignoradas` | Tags a ignorar. |
| `preferencias_usuario.tipo_fonte_preferido` | Ex.: `brasil_fisico`, `internacional`. |
| `preferencias_usuario.tamanho_resumo` | `curto`, `medio`, `longo`. |
| `preferencias_usuario.template_resumo_id` | Referência a template customizado. |
| `templates_resumo_usuario.system_prompt` | Instrução personalizada injetada no prompt. |

### 6.2 Mapeamento de tamanho

| `tamanho_resumo` | Min itens | Max itens |
|------------------|-----------|-----------|
| `curto` | 3 | 5 |
| `medio` | 5 | 8 |
| `longo` | 8 | 12 |

### 6.3 Fluxo do prompt personalizado

1. Carregar contexto compartilhado (cache).
2. Carregar preferências do usuário (`get_preferencias_usuario`).
3. Se `template_resumo_id` definido, carregar `get_template_resumo` → `system_prompt`.
4. Montar prompt: **contexto compartilhado** + **preferências do usuário** + **instrução do template**.
5. Uma única chamada LLM; validação Pydantic; formatação WhatsApp.

---

## 7. Fluxo Single-Shot e Limite de Tools

O agente opera num **fluxo otimizado**: recebe o contexto total do dia numa **única injeção**, lê esse contexto, pode chamar as tools conforme budget, e **devolve imediatamente** o JSON final.

### 7.1 Limite de chamadas a tools

- **Budget total:** até 3 tool calls por persona/sessão (combinação de `obter_textos_brutos_cluster` e `buscar_na_web`).
- **`buscar_na_web`:** máximo 2 chamadas por sessão (conforme schema).
- **max_iterations:** 5 (inclui round-trips ao LLM e execução de tools).
- Ao atingir o limite sem JSON válido: falha controlada (log + erro).

### 7.2 Re-iteração permitida (validação Pydantic)

- Se o **Pydantic** rejeitar o JSON por violação de `max_length`, o script faz **uma vez** fallback ao LLM com `PROMPT_CORRECAO_PYDANTIC_V1`.
- Este é o único cenário de segunda chamada ao LLM por validação.

---

## 8. Seleção e Curadoria (Thresholding de Qualidade)

### 8.1 Critérios de oportunidade (calibração do prompt)

O prompt explicita o que o agente deve procurar:

- **Procure assimetrias.** Oportunidades envolvem: empresas em **stress financeiro**; decisões judiciais que liberam ou bloqueiam valores massivos; aprovações súbitas de M&A ou bloqueios regulatórios; alterações regulatórias que afetam a viabilidade de um setor; default, quebra de covenants, ativismo, mudanças de controle; NPLs, precatórios, dívida ativa, leilões relevantes.
- **Não selecione** resultados trimestrais de rotina, exceto se indicarem rutura de covenants ou sinal claro de distress.
- **Prioridade:** P1 > P2 > P3, mas um P3 pode entrar se for claramente oportunidade.
- **Cobertura por fonte:** Equilíbrio entre as três fontes quando houver conteúdo relevante.

### 8.2 Limites flexíveis

- **Até 12** itens no resumo final. **Não há mínimo.**
- Se o dia for fraco e apenas 3 factos atenderem aos critérios, retornar apenas 3.
- Proibido preencher espaço com notícias irrelevantes.

---

## 9. Formato de Saída e Entrega (WhatsApp)

### 9.1 Formatação

- **Cabeçalho:** Data, título "RESUMO DO DIA — SPECIAL SITUATIONS".
- **Seções (multi-persona):** 💀 DISTRESS / ⚖️ REGULATÓRIO / 🏛️ M&A.
- **Cada item:** Título curto + bullet de impacto + fontes (nomes reais dos jornais).
- **Rodapé:** Gerado pelo AlphaFeed.
- **Split:** Se > 4096 caracteres, divide em múltiplas mensagens.

### 9.2 Persistência e idempotência

- **`resumos_usuario`:** Um registro por `(user_id, data_referencia)` com `clusters_avaliados_ids`, `clusters_escolhidos_ids`, `texto_gerado`, `texto_whatsapp`, `prompt_version`, `metadados`.
- Envio via `POST /api/resumo/gerar` → background task → `create_resumo_usuario`.

---

## 10. Relação com Componentes Existentes

| Componente | Uso pelo agente de resumo diário |
|------------|----------------------------------|
| **CRUD** | `get_clusters_for_feed_by_date`, `get_textos_brutos_por_cluster_id`, `get_preferencias_usuario`, `get_template_resumo`. |
| **Prompts** | `PERSONAS_RESUMO_DIARIO` (multi-persona), `PROMPT_CORRECAO_PYDANTIC_V1`. |
| **Pipeline** | O agente roda **após** os clusters estarem prontos. Pode ser acionado por `POST /api/resumo/gerar` ou job agendado. |
| **Telegram Broadcaster** | Não substitui; o Telegram continua com briefing P1/P2. O WhatsApp recebe o resumo curado. |

---

## 11. Onde Está Implementado

| O que | Onde |
|-------|------|
| **Orquestrador** | `agents/resumo_diario/agent.py` |
| **Tools + Pydantic** | `agents/resumo_diario/tools/definitions.py` |
| **Endpoint** | `backend/main.py`: `POST /api/resumo/gerar` → `_generate_user_summary()` → `gerar_resumo_para_usuario()` |
| **Prompts** | `backend/prompts.py`: `PERSONAS_RESUMO_DIARIO`, `PROMPT_DISTRESSED_V1`, `PROMPT_REGULATORIO_V1`, `PROMPT_ESTRATEGISTA_V1`, `PROMPT_CORRECAO_PYDANTIC_V1` |

### Árvore de arquivos

```
agents/resumo_diario/
├── __init__.py
├── agent.py                      ← Orquestrador (gerar_resumo_diario, gerar_resumo_para_usuario)
└── tools/
    ├── __init__.py
    └── definitions.py            ← Pydantic + Gemini schema + execute_obter_textos_brutos, execute_buscar_na_web

backend/main.py                   ← POST /api/resumo/gerar → _generate_user_summary → gerar_resumo_para_usuario
backend/prompts.py                ← PERSONAS_RESUMO_DIARIO, PROMPT_CORRECAO_PYDANTIC_V1
```

---

## 12. Requisitos de Infra e Config

- **LLM:** Gemini; modelo `gemini-2.0-flash` (configurável).
- **API Keys:** `GEMINI_API_KEY` (obrigatória); `TIVALY_API_KEY` (para `buscar_na_web`; sem ela, tool retorna `unavailable`).
- **Banco:** Tabelas `preferencias_usuario`, `templates_resumo_usuario`, `resumos_usuario`.
- **WhatsApp:** Formatação pronta para envio; provedor a definir (API oficial, Twilio, etc.).

---

## 13. Contrato Pydantic (v3.1)

O LLM devolve um JSON validado por Pydantic. Esquema atual:

### ResumoDiarioContract

```python
class ResumoDiarioContract(BaseModel):
    tldr_executivo: Optional[str] = Field(None, max_length=300)
    clusters_selecionados: conlist(ClusterSelecionado, min_length=1, max_length=12)
```

### ClusterSelecionado

```python
class ClusterSelecionado(BaseModel):
    cluster_id: int
    secao: str = Field("geral", max_length=30)  # "distressed", "regulatorio", "estrategico", "geral"
    titulo_whatsapp: str = Field(..., max_length=100)
    bullet_impacto: str = Field(..., max_length=280)
    fonte_principal: str = Field(..., max_length=80)
```

| Campo | Restrição |
|-------|-----------|
| `tldr_executivo` | Opcional; max 300 caracteres |
| `clusters_selecionados` | 1 a 12 itens |
| `secao` | "distressed", "regulatorio", "estrategico" ou "geral" |
| `titulo_whatsapp` | Max 100 caracteres |
| `bullet_impacto` | Max 280 caracteres |
| `fonte_principal` | Max 80 caracteres |

---

## 14. Decisões e Riscos

| Decisão | Recomendação |
|---------|--------------|
| **Pasta do agente** | `agents/resumo_diario/` — responsabilidade única. |
| **Split/Merge** | **Não.** Agente é READ-ONLY. |
| **Modo padrão (terminal)** | v3.1 Unificado via `gerar_resumo_diario()` — 1 chamada LLM, 5 tools. |
| **Modo padrão (API)** | v3.0 Per-User via `POST /api/resumo/gerar` — 1 chamada LLM personalizada, 8 tools. |
| **Cache** | Compartilhado por data+updated_at; invalidado quando clusters mudam. |
| **Idempotência** | Um resumo por `(user_id, data)`. Re-gerar sobrescreve. |

---

## 15. Referência Técnica e Histórico de Versões

### 15.1 Funções do orquestrador (`agent.py`)

| Função | Responsabilidade |
|--------|------------------|
| `_build_context_block(db, date)` | Map-Reduce: recolhe todos os clusters do dia UMA VEZ. Retorna `(contexto_str, avaliados_ids, fontes_map)`. |
| `_run_llm_with_tools(db, prompt, persona_name, budget)` | Gemini Function Calling com `obter_textos_brutos_cluster` e `buscar_na_web`. Se budget=0, chama sem tools. |
| `_validate_and_fix(raw_json_str, persona_name)` | Pydantic + fallback com `PROMPT_CORRECAO_PYDANTIC_V1`. |
| `gerar_resumo_diario(date, prompt_template)` | **1 chamada LLM unificada** com `PROMPT_RESUMO_UNIFICADO_V1`. Budget: 5 tool calls. |
| `gerar_resumo_para_usuario(user_id, date)` | Modo Per-User: contexto em cache + prompt personalizado + 1 chamada LLM. Budget: 8 tool calls. |
| `formatar_whatsapp(resultado)` | Mensagem agrupada por seção temática (💀 → ⚖️ → 🏛️ → 📋), split se > 4096 chars. |

### 15.2 Seções temáticas (modo unificado)

| Seção | Emoji | Escopo |
|-------|-------|--------|
| **distressed** | 💀 | RJ, NPLs, falências, covenants, inadimplência CVM |
| **regulatorio** | ⚖️ | STF/STJ, CARF, CADE, regulações, decisões tributárias |
| **estrategico** | 🏛️ | M&A, OPAs, turnarounds, mudanças de controle, privatizações |
| **geral** | 📋 | Eventos relevantes fora das categorias acima |

O LLM marca cada cluster com `secao` no JSON. O formatador agrupa automaticamente.

### 15.3 Histórico de versões

| Versão | Data | Mudanças |
|--------|------|----------|
| v1 | 2026-03-06 | Prompt monolítico. Selecionou Corinthians (esportes) incorretamente. |
| v2 (MULTI-PERSONA) | 2026-03-06 | 3 personas em paralelo; REGRA DE PROFUNDIDADE forçando tools; mensagem seccionada. |
| v3.0 (MULTI-TENANT) | 2026-03-15 | Per-User: `gerar_resumo_para_usuario()`, cache de contexto, preferências do banco, tool `buscar_na_web` (Tivaly). |
| v3.1 (UNIFICADO) | 2026-03-15 | Substituiu 3 personas por 1 chamada unificada (`PROMPT_RESUMO_UNIFICADO_V1`). Campo `secao` no `ClusterSelecionado`. Budget: 5 tools. Custo ~60% menor. |

### 15.4 Normalização de Fontes

Os nomes de fontes (jornais/portais) passam por `normalizar_fonte_display()` em `backend/utils.py` antes de serem exibidos:
- Mapeia aliases para nomes bonitos (ex: "SP O Estado de S Paulo - 150326" → "O Estado de S.Paulo").
- Filtra lixo (usernames, valores tipo "ines249", "json_dump").
- Whitelist de ~30 fontes conhecidas.

### 15.5 Pendências conhecidas

- [ ] Módulo de envio WhatsApp (provedor a definir).
- [ ] Tabela `resumos_enviados_whatsapp` para idempotência global.
- [ ] Extrair modelo Gemini para config/env.
- [x] Telegram Listener: `TELEGRAM_LISTENER/` (Telethon, user account, sem bot). Ver `TELEGRAM_LISTENER/README.md`.

---

**Fim do documento.** Este spec deve ser usado como referência única para o agente de resumo diário. Atualizar `docs/SYSTEM.md` e `docs/OPERATIONS.md` quando houver novos endpoints, tabelas ou variáveis de ambiente.
