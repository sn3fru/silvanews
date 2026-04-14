# Guia: Como Adicionar um Novo Perfil de Usuário ao AlphaFeed

> **Objetivo:** Passo a passo completo para integrar um novo perfil de resumo personalizado ao sistema, desde a auditoria de notícias até a documentação final.
>
> **Referência:** Perfil "Barretti" (Capital Solutions) como caso de uso real.
>
> **Última atualização:** 2026-04-14

---

## Índice

1. [Decisão Inicial: Slot ou Prompt Dedicado?](#1-decisão-inicial-slot-ou-prompt-dedicado)
2. [Passo 1 — Auditoria do Pipeline de Notícias](#2-passo-1--auditoria-do-pipeline-de-notícias)
3. [Passo 2 — Criar o Usuário e Preferências](#3-passo-2--criar-o-usuário-e-preferências)
4. [Passo 3 — Avaliar o Contrato Pydantic](#4-passo-3--avaliar-o-contrato-pydantic)
5. [Passo 4 — Criar ou Reutilizar o Prompt](#5-passo-4--criar-ou-reutilizar-o-prompt)
6. [Passo 5 — Implementar Funções do Agente](#6-passo-5--implementar-funções-do-agente)
7. [Passo 6 — Integrar no Workflow](#7-passo-6--integrar-no-workflow)
8. [Passo 7 — Testar e Validar](#8-passo-7--testar-e-validar)
9. [Passo 8 — Atualizar Documentação](#9-passo-8--atualizar-documentação)
10. [Checklist Final](#10-checklist-final)
11. [Referência: Arquivos e Funções-Chave](#11-referência-arquivos-e-funções-chave)
12. [Armadilhas Comuns](#12-armadilhas-comuns)

---

## 1. Decisão Inicial: Slot ou Prompt Dedicado?

Antes de tudo, avalie o nível de customização que o novo perfil precisa:

### Opção A: Usar os Slots do PROMPT_MASTER_V2 (leve, rápido)

**Quando usar:**
- O formato de saída padrão (título + bullet + fonte, max 15 itens) atende
- O novo perfil precisa apenas de foco em empresas, teses ou tags diferentes
- Não precisa de campos extras por notícia (ex: "por que importa", "follow-ups")

**O que fazer:**
- Criar usuário + `PreferenciaUsuario` com `config_extra` preenchido
- Preencher `empresas_radar`, `teses_juridicas`, `instrucoes_resumo`
- O sistema já roda `gerar_resumo_para_usuario()` automaticamente

**Nenhum código novo é necessário** — apenas dados no banco.

### Opção B: Prompt Dedicado (pesado, máxima qualidade)

**Quando usar:**
- O formato de saída é radicalmente diferente (ex: 7 campos por notícia, blocos finais)
- O prompt do usuário tem 2000+ palavras com regras específicas
- Tentar comprimir no slot `{INSTRUCAO_LIVRE_USUARIO}` destruiria a qualidade

**O que fazer:**
- Criar prompt dedicado (`PROMPT_NOVOPERFIL_V1`)
- Criar contrato Pydantic dedicado (`ResumoNovoPerfilContract`)
- Criar funções dedicadas (`gerar_resumo_novoperfil()`, `formatar_novoperfil()`)
- Rotear no workflow via `config_extra.perfil`

**Exemplo real:** Perfil Barretti usou Opção B.

### Tabela Comparativa

| Aspecto | Opção A (Slots) | Opção B (Dedicado) |
|---------|-----------------|---------------------|
| Código novo | 0 linhas | ~300-500 linhas |
| Prompt | PROMPT_MASTER_V2 + slots | Prompt inteiramente novo |
| Pydantic | ResumoDiarioContract (existente) | Contrato novo |
| Formatação | formatar_whatsapp() (existente) | Formatador novo |
| Chamadas LLM extras | 1 (compartilhada com per-user) | 1 (dedicada) |
| Tempo de implementação | 10 min (só DB) | 2-4 horas |

---

## 2. Passo 1 — Auditoria do Pipeline de Notícias

**Pergunta central:** As notícias que o novo perfil considera importantes estão chegando até os clusters ativos?

### 2.1 Camadas de filtragem (de cima para baixo)

O pipeline tem **5 pontos** onde notícias podem ser removidas antes de chegar ao resumo:

| Camada | Arquivo | Função | O que remove |
|--------|---------|--------|-------------|
| **1. Higienização** | `process_articles.py` | `higienizar_lote_artigos()` | Culinária, astrologia, fofoca, esporte — via `PROMPT_HIGIENIZACAO_V1` |
| **2. Fato gerador** | `process_articles.py` | `processar_artigo_sem_cluster()` | Artigos que falham na extração → status `erro` |
| **3. Agente Materialidade** | `process_articles.py` | `classificar_e_resumir_cluster()` | Empurra clusters para P3 via `PROMPT_AGENTE_MATERIALIDADE_V1` |
| **4. Classificação** | `process_articles.py` | `classificar_e_resumir_cluster()` | Marca como IRRELEVANTE via `PROMPT_ANALISE_E_SINTESE_CLUSTER_V1` |
| **5. Rejeição no resumo** | `backend/prompts.py` | `_REJEICAO_MACRO_PERSONAS` | Macro genérico, estatais, esportes — filtra no momento do resumo |

### 2.2 Como auditar

Para cada tema que o novo perfil precisa, verifique:

**a) O tema está sendo capturado pelas fontes?**
```
Fontes ativas: Valor, Jota, Conjur, Migalhas, Brazil Journal + PDFs
```
Se o perfil precisa de fontes internacionais específicas (ex: FT, WSJ) e elas não estão sendo coletadas, será necessário adicionar um crawler em `CRAWLERS/`.

**b) O tema está sobrevivendo à higienização?**
- Consulte `PROMPT_HIGIENIZACAO_V1` em `backend/prompts.py` (~linha 650)
- Se o tema parece "soft" (ex: ESG, cultura corporativa), verifique se não é classificado como irrelevante

**c) O tema está recebendo P1/P2 ou sendo rebaixado a P3?**
- Consulte as listas `P1_ITENS`, `P2_ITENS`, `P3_ITENS` em `backend/prompts.py` (~linhas 307-376)
- Se o tema do novo perfil não está em P1/P2, ele pode ser consistentemente P3
- Nota: P3 ainda aparece no contexto do agente (com resumo curto), mas com menor destaque

**d) O tema está sendo rejeitado pelo `_REJEICAO_MACRO_PERSONAS`?**
- Em `backend/prompts.py` (~linha 1468)
- Este bloco rejeita: macro genérico (PIB, Selic sem crash), estatais puras, esportes
- **Importante:** Se o novo perfil QUER macro (ex: porque impacta funding/crédito), o prompt dedicado (Opção B) pode usar uma versão modificada deste bloco

### 2.3 Exemplo prático (Barretti)

| Tema | Capturado? | Sobrevive higienização? | Prioridade | No resumo? |
|------|-----------|------------------------|-----------|-----------|
| RJ/Falência | Sim (Valor, Jota) | Sim | P1 | Sim |
| M&A/venda ativos | Sim | Sim | P1/P2 | Sim |
| Macro c/ impacto crédito | Sim | Sim | P2/P3 | **Rejeitado pelo `_REJEICAO_MACRO_PERSONAS` default** |
| STF/STJ/regulatório | Sim (Jota, Conjur) | Sim | P2 | Sim |

**Resultado da auditoria Barretti:** O pipeline captura tudo, mas o `_REJEICAO_MACRO_PERSONAS` do resumo default rejeita macro genérico. Solução: prompt dedicado com `_REJEICAO_BARRETTI` mais permissivo.

### 2.4 Tags disponíveis no sistema

**Nacionais (9):** M&A e Transações Corporativas, Jurídico/Falências/Regulatório, Dívida Ativa e Créditos Públicos, Distressed Assets e NPLs, Mercado de Capitais e Finanças Corporativas, Política Econômica (Brasil), Infraestrutura e Concessões, Agro e Commodities, Imobiliário e Fundos

**Internacionais (8):** Global M&A, Global Legal and Regulatory, Sovereign Debt and Credit, Global Distressed, Global Capital Markets, Central Banks, Geopolitics and Trade, Technology and Innovation

Se o novo perfil precisa de temas que não se encaixam nessas tags, avalie se é necessário criar novas tags (raro — geralmente os temas se encaixam nas existentes).

---

## 3. Passo 2 — Criar o Usuário e Preferências

### 3.1 Seed no banco (recomendado para perfis fixos)

Adicione em `backend/database.py`, dentro de `init_database()`, após o seed do admin e do barretti:

```python
# Seed usuario [nome_perfil]
try:
    user_exists = db.query(Usuario).filter(
        Usuario.email == "email@dominio.com"
    ).first()
    if not user_exists:
        import hashlib, secrets
        _pwd = os.getenv("NOVOPERFIL_PASSWORD", "senha_padrao")
        _salt = secrets.token_hex(16)
        _hash = f"{_salt}${hashlib.sha256((_salt + _pwd).encode()).hexdigest()}"
        new_user = Usuario(
            nome="Nome Completo",
            email="email@dominio.com",
            senha_hash=_hash,
            role="user",
            ativo=True,
        )
        db.add(new_user)
        db.flush()

        new_prefs = PreferenciaUsuario(
            user_id=new_user.id,
            tags_interesse=[],          # vazio = todas as tags
            tags_ignoradas=[],
            tamanho_resumo="longo",     # curto | medio | longo
            config_extra={
                "empresas_radar": "Empresa1, Empresa2, Empresa3",
                "teses_juridicas": "tese1, tese2, tese3",
                "instrucoes_resumo": "NOVOPERFIL_INSTRUCTIONS",
                "perfil": "nome_perfil",  # identificador para routing
            },
        )
        db.add(new_prefs)
        db.commit()
        print("✅ Usuario [nome_perfil] criado")
except Exception as e:
    db.rollback()
    print(f"⚠️ Seed [nome_perfil] falhou: {e}")
```

### 3.2 Campos críticos do `config_extra`

| Campo | Obrigatório? | Efeito |
|-------|-------------|--------|
| `perfil` | Sim (se Opção B) | Usado em `run_resumo_diario()` para routing |
| `empresas_radar` | Não | Injetado no slot `{EMPRESAS_RADAR}` do PROMPT_MASTER_V2 |
| `teses_juridicas` | Não | Injetado no slot `{TESES_JURIDICAS}` |
| `instrucoes_resumo` | **Sim** | Necessário para `user_has_custom_prefs()` retornar True |

**ATENÇÃO:** Se `config_extra` tiver apenas `perfil` sem `instrucoes_resumo`, `empresas_radar`, `teses_juridicas`, **e** `tags_interesse` for vazio, o usuário **não entrará** no loop de resumos personalizados. A função `user_has_custom_prefs()` em `backend/crud.py` verifica esses campos.

### 3.3 Domínios permitidos para auto-registro

Se o usuário precisar se registrar pela API (não por seed), o email deve pertencer a um domínio da whitelist em `backend/main.py`:

```python
_ALLOWED_DOMAINS = ["enforcegroup.com.br", "btgpactual.com", "btg.com", "btg.com.br"]
```

Para outros domínios, o admin precisa criar via `POST /api/auth/register`.

---

## 4. Passo 3 — Avaliar o Contrato Pydantic

### 4.1 O formato padrão atende?

O `ResumoDiarioContract` produz:

```
tldr_executivo: "2-3 frases panorama" (max 600 chars)
clusters_selecionados: [
    {
        cluster_id: 123,
        secao: "distressed",                    # Literal de 5 opções
        titulo_whatsapp: "💀 Título" (max 120),
        bullet_impacto: "Análise..." (max 400),
        fonte_principal: "Valor" (max 80)
    }
]   # 1 a 15 itens
```

**Se este formato é suficiente → Use Opção A (Slots), sem criar contrato novo.**

### 4.2 Quando criar contrato dedicado

Crie um novo contrato quando o perfil precisa de:

| Necessidade | Exemplo |
|-------------|---------|
| Mais campos por notícia | "por que importa", "follow-ups", "acionabilidade" |
| Blocos finais de síntese | "radar de oportunidades", "watchlist", "action items" |
| Priorização diferente | "Alta/Media/Baixa" em vez de seção temática |
| Limites diferentes | Min 7 noticias (vs max 15), resumos de 2000 chars (vs 400) |

### 4.3 Template para contrato dedicado

Em `agents/resumo_diario/tools/definitions.py`:

```python
class NovoPerfilNoticiaContract(BaseModel):
    """Campos por notícia — ajustar conforme necessidade do perfil."""
    cluster_id: int
    titulo: str = Field(..., max_length=200)
    # ... campos específicos do perfil ...
    fonte_principal: str = Field(..., max_length=100)


class ResumoNovoPerfilContract(BaseModel):
    """Contrato completo do resumo — ajustar blocos finais."""
    noticias: conlist(NovoPerfilNoticiaContract, min_length=5, max_length=25)
    # ... blocos finais específicos ...
```

**Dicas:**
- Use `Literal` para campos com valores fixos (evita que o LLM invente)
- Use `max_length` generosamente — o LLM frequentemente excede limites curtos
- Use `default_factory=list` para campos opcionais (blocos finais podem ficar vazios)
- `min_length` nos itens obrigatórios garante que o LLM não entregue um resumo vazio

---

## 5. Passo 4 — Criar ou Reutilizar o Prompt

### 5.1 Opção A: Reutilizar PROMPT_MASTER_V2

Nenhum prompt novo. Os slots são preenchidos automaticamente por `_build_user_prompt()`:

- `{TAGS_FOCO}` ← `tags_interesse`
- `{EMPRESAS_RADAR}` ← `config_extra.empresas_radar`
- `{TESES_JURIDICAS}` ← `config_extra.teses_juridicas`
- `{INSTRUCAO_LIVRE_USUARIO}` ← `config_extra.instrucoes_resumo`
- `{MIN_ITENS}` / `{MAX_ITENS}` ← derivados de `tamanho_resumo`

### 5.2 Opção B: Prompt dedicado

Adicione uma nova constante em `backend/prompts.py`:

```python
PROMPT_NOVOPERFIL_V1 = """
[Texto do usuário reaproveitado na íntegra]

[Adaptações mínimas: "PDF" → "clusters", etc.]

[Bloco de tools reaproveitado do chassis]

[Formato JSON alinhado ao contrato Pydantic]

<<< CONTEXTO DO DIA >>>
{CONTEXTO_CLUSTERS_DIA}
"""
```

**Estrutura recomendada (baseada no Barretti):**

1. **Bloco de rejeição adaptado** — Reaproveitar de `_REJEICAO_MACRO_PERSONAS`:
   - Cobertura de fontes (brasil_fisico/online/internacional)
   - Regra anti-repetição (contexto de ontem)
   - Regra anti-alucinação
   - **Remover** rejeições que conflitem com o perfil (ex: se o perfil quer macro)

2. **Texto do usuário na íntegra** — Papel, contexto profissional, critérios, eixos temáticos, sistema de priorização, tags, formato por notícia, blocos finais, regras de qualidade

3. **Adaptações mínimas** — Trocar "PDF" por "clusters", remover instruções de processamento por arquivo/jornal, ajustar mínimos

4. **Bloco de tools** — Instruções para `obter_textos_brutos_cluster` e `buscar_na_web`

5. **Formato JSON** — Alinhado ao contrato Pydantic, com exemplo completo

**Placeholder obrigatório:** `{CONTEXTO_CLUSTERS_DIA}` — preenchido por `_build_context_block()`

**Placeholder opcional:** `{MAX_TOOL_CALLS}` — se quiser parametrizar o budget de tools

### 5.3 Dicas para o prompt

- **Duplas chaves** para literais JSON: `{{` e `}}` (senão o `.format()` falha)
- **Não use** `{` ou `}` sozinhos no texto do usuário — escape para `{{` e `}}`
- **Teste o prompt** com `get_prompt("PROMPT_NOVOPERFIL_V1")` antes de rodar o LLM
- **max_output_tokens**: Se o output será muito maior que o padrão (8192), passe parâmetro maior (ex: 16384)

---

## 6. Passo 5 — Implementar Funções do Agente

**Arquivo:** `agents/resumo_diario/agent.py`

### 6.1 Opção A: Nenhum código novo

O `gerar_resumo_para_usuario()` já faz tudo. Pronto.

### 6.2 Opção B: Funções dedicadas

Precisa de **3 funções**:

#### a) `_validate_and_fix_novoperfil(raw_json_str)`

```python
def _validate_and_fix_novoperfil(raw_json_str: str) -> ResumoNovoPerfilContract:
    """Valida JSON do LLM com contrato dedicado. Fallback via LLM se falhar."""
    data = _extract_json_from_text(raw_json_str)
    if data is None:
        raise ValueError(f"Impossível extrair JSON: {raw_json_str[:500]}")

    # Sanitizar campos com Literals — corrigir valores inválidos
    for n in data.get("noticias", []):
        if isinstance(n, dict):
            # Ajustar campos Literal inválidos para defaults seguros
            pass

    try:
        return ResumoNovoPerfilContract(**data)
    except ValidationError as e:
        # Fallback: chamar LLM com PROMPT_CORRECAO_PYDANTIC_V1
        # (copiar padrão de _validate_and_fix_barretti)
        ...
```

#### b) `gerar_resumo_novoperfil(target_date)`

```python
def gerar_resumo_novoperfil(target_date=None) -> Dict[str, Any]:
    """Gera resumo no formato do novo perfil."""
    # 1. Resolver data
    # 2. Importar prompt: from backend.prompts import PROMPT_NOVOPERFIL_V1
    # 3. Construir contexto: _build_context_block() (compartilhado, com cache)
    # 4. Formatar prompt: .format(CONTEXTO_CLUSTERS_DIA=contexto)
    # 5. Chamar LLM: _run_llm_with_tools(db, prompt, persona_name="novoperfil",
    #                                     tool_call_budget=N, max_output_tokens=M)
    # 6. Validar: _validate_and_fix_novoperfil(raw_response)
    # 7. Retornar dict com ok, contract_dict, clusters, etc.
```

**Parâmetros-chave para ajustar:**
- `tool_call_budget`: Default=5, per-user=8, Barretti=10. Mais noticias = mais budget.
- `max_output_tokens`: Default=8192, Barretti=16384. Proporcional ao tamanho do output.

#### c) `formatar_novoperfil(resultado)`

```python
def formatar_novoperfil(resultado: Dict[str, Any]) -> str:
    """Formata o resultado em texto legível."""
    contract_dict = resultado.get("contract_dict", {})
    lines = []
    # Montar header
    # Iterar noticias
    # Montar blocos finais
    return "\n".join(lines)
```

### 6.3 Atualizar imports

Em `agents/resumo_diario/agent.py`, adicionar o novo contrato nos imports:

```python
from agents.resumo_diario.tools.definitions import (
    ResumoDiarioContract,
    ResumoBarrettiContract,
    ResumoNovoPerfilContract,   # ← adicionar
    ...
)
```

---

## 7. Passo 6 — Integrar no Workflow

**Arquivo:** `run_complete_workflow.py`, função `run_resumo_diario()`

### 7.1 Opção A: Nenhuma alteração

O loop existente já chama `gerar_resumo_para_usuario()` para quem tem `user_has_custom_prefs() == True`.

### 7.2 Opção B: Adicionar branch de routing

Na Fase 2 do `run_resumo_diario()`, adicionar um `elif` para o novo perfil:

```python
for user, prefs in custom_users:
    perfil = (prefs.config_extra or {}).get("perfil", "")

    if perfil == "barretti":
        # ... (existente)
    elif perfil == "novoperfil":
        from agents.resumo_diario.agent import gerar_resumo_novoperfil, formatar_novoperfil
        res_user = gerar_resumo_novoperfil(target_date=target_date)
        if res_user.get("ok"):
            texto = formatar_novoperfil(res_user)
            print(f"\n{'=' * 60}")
            print(f"  RESUMO DO DIA — [NOME DO PERFIL]")
            print(f"{'=' * 60}")
            print(texto)
            # Salvar no banco (create_resumo_usuario)
    else:
        # Fluxo per-user genérico (existente)
```

---

## 8. Passo 7 — Testar e Validar

### 8.1 Script temporário

Criar `tmp_test_novoperfil.py` (deletar após validação):

```python
import os

# Carregar .env
_env_path = os.path.join(os.path.dirname(__file__), "backend", ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if key.strip() and not os.getenv(key.strip()):
                os.environ[key.strip()] = val

from backend.database import init_database
init_database()

from agents.resumo_diario.agent import gerar_resumo_novoperfil, formatar_novoperfil

res = gerar_resumo_novoperfil()
if res.get("ok"):
    print(formatar_novoperfil(res))
else:
    print(f"ERRO: {res.get('error')}")
```

### 8.2 O que verificar

| Critério | Como verificar |
|----------|---------------|
| Notícias esperadas aparecem? | Comparar com o feed do dia no frontend |
| Menções obrigatórias presentes? | Buscar strings no output (BTG, etc.) |
| Formato correto? | Todos os campos preenchidos no JSON |
| Pydantic passou? | Sem fallback de correção nos logs |
| Volume adequado? | Min/max de noticias respeitado |
| Sem alucinação? | Dados factuais batem com os clusters |
| Tools foram usadas? | Logs mostram tool calls |

### 8.3 Deletar o script após validação

Regra do projeto: scripts temporários não ficam no repositório.

---

## 9. Passo 8 — Atualizar Documentação

### 9.1 Arquivos a atualizar (obrigatório)

| Arquivo | O que adicionar |
|---------|-----------------|
| `docs/SYSTEM.md` | Fluxo do novo perfil na seção 10a, prompt na tabela de prompts (seção 7) |
| `docs/AGENTE_RESUMO_DIARIO_SPEC.md` | Modo na tabela 1.2, contrato na seção 13, funções na seção 15.1, versão no histórico 15.3 |
| `.cursorrules` | Referência ao perfil na seção do agente de resumo |

### 9.2 Variáveis de ambiente

Se o perfil usa senha configurável via env var (ex: `NOVOPERFIL_PASSWORD`), adicionar em:
- `.cursorrules` (seção ENV VARS OPCIONAIS)
- `docs/SYSTEM.md` (seção 12: Variáveis de Ambiente)

---

## 10. Checklist Final

```
PRÉ-IMPLEMENTAÇÃO
[ ] Auditei o pipeline: as notícias que o perfil precisa estão chegando?
[ ] Decidi: Opção A (Slots) ou Opção B (Prompt Dedicado)?
[ ] Se Opção B: recebi o prompt do usuário e identifiquei adaptações necessárias

IMPLEMENTAÇÃO
[ ] Criei o usuário + PreferenciaUsuario (seed ou API)
[ ] config_extra tem pelo menos instrucoes_resumo (para user_has_custom_prefs)
[ ] config_extra.perfil está definido (para routing, se Opção B)

SE OPÇÃO B:
[ ] Criei contrato Pydantic em agents/resumo_diario/tools/definitions.py
[ ] Criei prompt em backend/prompts.py
[ ] Criei gerar_resumo_*() em agents/resumo_diario/agent.py
[ ] Criei _validate_and_fix_*() em agents/resumo_diario/agent.py
[ ] Criei formatar_*() em agents/resumo_diario/agent.py
[ ] Atualizei imports no agent.py
[ ] Adicionei branch de routing em run_complete_workflow.py

VALIDAÇÃO
[ ] Testei com script temporário
[ ] Output tem o formato esperado
[ ] Notícias relevantes presentes
[ ] Pydantic validou sem fallback
[ ] Deletei o script temporário

DOCUMENTAÇÃO
[ ] Atualizei docs/SYSTEM.md
[ ] Atualizei docs/AGENTE_RESUMO_DIARIO_SPEC.md
[ ] Atualizei .cursorrules
```

---

## 11. Referência: Arquivos e Funções-Chave

| Arquivo | Função/Constante | Papel |
|---------|-----------------|-------|
| `backend/prompts.py` | `_REJEICAO_MACRO_PERSONAS` | Regras de rejeição no resumo (macro, esportes, estatais) |
| `backend/prompts.py` | `PROMPT_MASTER_V2` | Chassis + slots para per-user genérico |
| `backend/prompts.py` | `PROMPT_BARRETTI_V1` | Exemplo de prompt dedicado |
| `backend/prompts.py` | `P1_ITENS`, `P2_ITENS`, `P3_ITENS` | Listas de prioridade do classificador |
| `backend/prompts.py` | `TAGS_SPECIAL_SITUATIONS` | Tags nacionais (9 categorias) |
| `backend/database.py` | `init_database()` | Seed de usuários |
| `backend/database.py` | `PreferenciaUsuario` | Modelo ORM de preferências |
| `backend/crud.py` | `user_has_custom_prefs()` | Determina quem recebe resumo personalizado |
| `agents/resumo_diario/agent.py` | `_build_context_block()` | Monta contexto compartilhado (cache) |
| `agents/resumo_diario/agent.py` | `_build_user_prompt()` | Preenche slots do PROMPT_MASTER_V2 |
| `agents/resumo_diario/agent.py` | `_run_llm_with_tools()` | Executa LLM com tools (budget + max_output_tokens) |
| `agents/resumo_diario/agent.py` | `gerar_resumo_para_usuario()` | Resumo per-user genérico (Opção A) |
| `agents/resumo_diario/agent.py` | `gerar_resumo_barretti()` | Exemplo de resumo dedicado (Opção B) |
| `agents/resumo_diario/tools/definitions.py` | `ResumoDiarioContract` | Contrato padrão |
| `agents/resumo_diario/tools/definitions.py` | `ResumoBarrettiContract` | Exemplo de contrato dedicado |
| `run_complete_workflow.py` | `run_resumo_diario()` | Orquestra Fase 1 (default) + Fase 2 (per-user + perfis) |
| `process_articles.py` | `classificar_e_resumir_cluster()` | Classificação + P1/P2/P3 + tag |
| `process_articles.py` | `higienizar_lote_artigos()` | Remoção de lixo (Etapa 1.5) |

---

## 12. Armadilhas Comuns

### 12.1 Usuário não aparece no loop de resumos

**Causa:** `user_has_custom_prefs()` retorna False.
**Solução:** Garantir que `config_extra` tenha pelo menos `instrucoes_resumo`, `empresas_radar` ou `teses_juridicas` preenchidos, OU que `tags_interesse` não seja vazio.

### 12.2 Prompt com chaves quebra o `.format()`

**Causa:** `{` ou `}` literais no texto do prompt (ex: JSON de exemplo).
**Solução:** Escapar com `{{` e `}}`. Teste: `prompt.format(CONTEXTO_CLUSTERS_DIA="teste")`.

### 12.3 LLM excede max_length do Pydantic

**Causa:** Campos como `resumo_executivo` (max 2000) podem ser excedidos pelo LLM.
**Solução:** Na função `_validate_and_fix_*`, truncar campos antes de validar. Ou aumentar `max_length`.

### 12.4 LLM inventa valores de Literal

**Causa:** O LLM pode retornar "Média" em vez de "Media" (com acento), ou "Monitorar" em vez de "Monitorar de perto".
**Solução:** Na função `_validate_and_fix_*`, sanitizar valores de campos Literal para os valores válidos antes da validação Pydantic.

### 12.5 Poucas notícias no output

**Causa:** `min_length` do contrato Pydantic é maior que o número de clusters relevantes.
**Solução:** Usar `min_length` realista. Se o dia for fraco, o LLM não consegue inventar 7+ notícias de qualidade.

### 12.6 Output truncado (token limit)

**Causa:** `max_output_tokens=8192` insuficiente para output rico.
**Solução:** Aumentar para 16384 (Barretti usa esse valor). O parâmetro é passado para `_run_llm_with_tools()`.

### 12.7 Tool calls insuficientes

**Causa:** Budget de tools muito baixo para o número de noticias que precisam de aprofundamento.
**Solução:** Aumentar `tool_call_budget`. Referência: default=5, per-user=8, Barretti=10.

### 12.8 Esquecer de registrar no PROMPT_REQUIRED_VARS

Se o novo prompt tem placeholders, registre em `PROMPT_REQUIRED_VARS` no final de `backend/prompts.py` para que `validar_prompt_update()` funcione.

---

**Fim do guia.** Usar em conjunto com `docs/SYSTEM.md` e `docs/AGENTE_RESUMO_DIARIO_SPEC.md` para referência completa do sistema.
