# Auditoria — Código para correção cirúrgica (agrupamento)

Este documento reúne os trechos exatos onde a lógica quebra, conforme diagnóstico de negócio (Buraco Negro, Fallback Regex, Silo tipo_fonte, Higienização, Fato Gerador).

---

## 1. Orquestrador de agrupamento (`process_articles.py`)

### 1.1 Constante que define o lote (origem do cognitive overload)

```python
# process_articles.py, linhas ~81-84
BATCH_SIZE_AGRUPAMENTO = 200  # Lotes maiores para melhor agrupamento (ordenados alfabeticamente antes do envio)
MAX_OUTPUT_TOKENS_STAGE2 = 32768
MAX_TRECHO_CHARS_STAGE2 = 120
```

### 1.2 Função `extrair_grupos_agrupamento_seguro` (fallback que cria "Outras notícias")

Quando o LLM devolve JSON inválido/truncado, o código cai aqui e o regex agrupa tudo o que conseguir num tema genérico (ex.: "Outras notícias e notas diversas"):

```python
# process_articles.py, linhas 379-465
def extrair_grupos_agrupamento_seguro(resposta: str) -> Optional[List[Dict[str, Any]]]:
    """
    Extrai grupos de agrupamento de forma tolerante a erros para ETAPA 2 (agrupamento em lote).
    1) Tenta via extrair_json_da_resposta (JSON completo válido)
    2) Fallback: usa regex para capturar blocos com "tema_principal" e "ids_originais"
       mesmo se o JSON estiver truncado/quebrado. Deduplica temas e normaliza ids.
    Retorna lista de objetos {"tema_principal": str, "ids_originais": [int, ...]} ou None.
    """
    try:
        status, bruto = extrair_json_da_resposta(resposta)
        if status.startswith('SUCESSO') and isinstance(bruto, list):
            return bruto

        import re
        grupos_map: Dict[str, set] = {}

        padrao = re.compile(
            r"\{\s*\"tema_principal\"\s*:\s*\"(.*?)\"\s*,\s*\"ids_originais\"\s*:\s*\[([\s\S]*?)\]\s*\}",
            re.DOTALL | re.IGNORECASE,
        )
        encontrados = list(padrao.finditer(resposta))

        for m in encontrados:
            tema = (m.group(1) or "").strip()
            ids_str = m.group(2) or ""
            # ... extração de ids ...
            if tema not in grupos_map:
                grupos_map[tema] = set()
            grupos_map[tema].update(ids)

        # Passo 2: Fallback ainda mais tolerante (tema + ids próximos, mesmo sem colchete de fechamento)
        if not grupos_map:
            try:
                tema_iter = re.finditer(r'"tema_principal"\s*:\s*"([^"]+)"', resposta, re.IGNORECASE)
                # ... acumula em grupos_map ...
            except Exception:
                pass

        if not grupos_map:
            return None

        grupos = [
            {"tema_principal": tema, "ids_originais": sorted(list(ids_set))}
            for tema, ids_set in grupos_map.items()
        ]

        print(f"🔁 Fallback agrupamento: recuperados {len(grupos)} grupos via regex seguro")
        return grupos
    except Exception as e:
        print(f"❌ ERRO: Fallback de extração de grupos falhou: {e}")
        return None
```

**Problema:** Se o LLM devolver um único bloco com tema genérico (ex. "Outras notícias e notas diversas") e uma lista enorme de ids, o regex aceita e o código cria um cluster com 157 artigos. O fallback não rejeita temas genéricos nem impõe limite de tamanho por grupo.

### 1.3 Uso do fallback em `agrupar_noticias_com_prompt` (try/except + continue)

O fluxo que dispara o fallback e depois processa o resultado sem validar tema nem tamanho:

```python
# process_articles.py, dentro de _processar_lotes, ~2125-2202
try:
    response = client.generate_content(prompt_completo, generation_config={...})
    if not response.text:
        print(f"⚠️ AVISO: API retornou resposta vazia ...")
        continue

    grupos_brutos = extrair_grupos_agrupamento_seguro(response.text)  # <-- aqui cai no fallback se JSON inválido

    if not grupos_brutos or not isinstance(grupos_brutos, list):
        print(f"❌ ERRO: Resposta de agrupamento inválida ...")
        continue

    print(f"✅ SUCESSO LOTE ... {len(grupos_brutos)} grupos criados.")

    for grupo_data in grupos_brutos:
        try:
            tema_principal = grupo_data.get("tema_principal", f"Grupo Lote {rotulo} {num_lote}")
            ids_no_lote = grupo_data.get("ids_originais", [])
            artigos_do_grupo = [...]
            # ... cria cluster com tema_principal sem validar se é genérico nem se len(ids) > 10
            print(f"  ✅ Grupo: '{tema_principal[:100]}' ({tipo_fonte}) - {len(artigos_do_grupo)} artigos")
        except Exception as e:
            print(f"  ❌ Erro ao processar grupo ...")
            continue

except Exception as e_lote:
    print(f"❌ ERRO CRÍTICO ao processar o lote ...")
    continue  # Pula para o próximo lote
```

**Problema:** Não há rejeição de `tema_principal` genérico ("Outras notícias", "Diversos", etc.) nem recusa de grupos com mais de 10 artigos quando a resposta veio do fallback.

### 1.4 Etapa 4 — `consolidacao_final_clusters` (IFs que impedem merge por tipo_fonte)

Trecho que bloqueia o merge quando há mistura internacional vs brasil_* (e onde se poderia permitir consolidação por evento):

```python
# process_articles.py, linhas 1207-1223 (dentro do loop de sugestões de merge)
# CORREÇÃO: Verifica se os clusters têm tipos_fonte compatíveis
try:
    fonte_objs = [db.query(ClusterEvento).filter(ClusterEvento.id == int(fid)).first() for fid in fontes]
    fonte_objs = [f for f in fonte_objs if f is not None]
    if destino_obj and fonte_objs:
        tipo_destino = getattr(destino_obj, 'tipo_fonte', 'nacional') or 'nacional'
        tipos_fontes = [getattr(f, 'tipo_fonte', 'nacional') or 'nacional' for f in fonte_objs]
        # Bloqueia qualquer mistura entre internacional e brasil_*
        misturando_internacional = (
            (tipo_destino == 'internacional' and any(tf != 'internacional' for tf in tipos_fontes)) or
            (tipo_destino != 'internacional' and any(tf == 'internacional' for tf in tipos_fontes))
        )
        if misturando_internacional:
            continue   # <-- ABORTA o merge (não chama merge_clusters)
except Exception:
    pass
```

**Problema:** Um mesmo evento (ex.: Jane Street) em cluster internacional e em cluster brasil_online/brasil_fisico nunca é consolidado na Etapa 4.

---

## 2. Aviso de incompatibilidade ao associar artigo a cluster (`backend/crud.py`)

A associação não é bloqueada; apenas regista o aviso. O “abortar” da consolidação acontece no bloco acima (Etapa 4), não aqui:

```python
# backend/crud.py, linhas 476-483 (dentro de associate_artigo_to_cluster)
# CORREÇÃO: Verifica compatibilidade de tipo_fonte entre artigo e cluster
tipo_fonte_artigo = getattr(artigo, 'tipo_fonte', 'nacional')
tipo_fonte_cluster = getattr(cluster, 'tipo_fonte', 'nacional')

if tipo_fonte_artigo != tipo_fonte_cluster:
    print(f"⚠️ AVISO: Incompatibilidade de tipo_fonte - artigo={tipo_fonte_artigo}, cluster={tipo_fonte_cluster}")
    # Não impede a associação, mas registra o aviso
```

---

## 3. Prompts oficiais (`backend/prompts.py`)

### 3.1 PROMPT_AGRUPAMENTO_V1

O prompt já proíbe "Outras notícias" e "Diversos", mas quando o LLM falha e o **fallback regex** é usado, essa proibição é ignorada — o regex aceita qualquer string em `tema_principal`:

```python
# backend/prompts.py, PROMPT_AGRUPAMENTO_V1 (resumo)
# LEIS ABSOLUTAS:
# 1. REGRA DE OURO: É estritamente PROIBIDO criar grupos genéricos como "Outras notícias", "Diversos", "Radar Macro" ...
# 2. REGRA DE IDENTIDADE: Dois artigos só pertencem ao mesmo cluster se, e só se, Entidade + Ação = MESMO EVENTO
# 3. LIMITE MECÂNICO: Nenhum grupo pode conter mais de 10 artigos
# 4. DEFAULT TO ISOLATION: Em dúvida, cluster de 1
```

**Conclusão:** O problema não é o texto do prompt; é o fallback que não aplica as mesmas regras (rejeitar tema genérico e grupos > 10).

### 3.2 PROMPT_HIGIENIZACAO_V1

Por que passou "Receita de pera com presunto": o prompt é restritivo (só marcar lixo quando for 100% receita/astrologia/desporto/fofoca sem ligação corporativa). Se o modelo interpretar que “pera com presunto” tem “mínima menção” a algo económico ou se a temperatura for alta, pode devolver `is_lixo: false`:

```python
# backend/prompts.py
PROMPT_HIGIENIZACAO_V1 = """Você é um filtro de lixo. Avalie os artigos abaixo.

Marque is_lixo: true APENAS E EXCLUSIVAMENTE se o texto for 100% sobre: culinária (receitas), astrologia, resultados desportivos puros, ou fofoca de celebridades sem ligação corporativa.

Se houver a MÍNIMA menção a impostos, bancos, empresas, governos, crimes financeiros ou greves, marque is_lixo: false.

Retorne um JSON válido, sem markdown, array com um objeto por artigo na MESMA ORDEM da entrada, cada um com "id" (índice 0-based) e "is_lixo" (boolean):
[{{"id": 0, "is_lixo": false}}, {{"id": 1, "is_lixo": true}}, ...]
"""
```

**Possíveis correções:** Endurecer exemplos (ex.: “receitas culinárias, incluindo pratos como X, Y” → sempre `is_lixo: true`); garantir temperatura 0 na chamada da Etapa 1.5.

### 3.3 PROMPT_EXTRACAO_FATO_GERADOR_V1 (limite de palavras)

O prompt pede “até 15 palavras”, mas o contrato Pydantic permite até 300 caracteres — daí factos geradores “prosaicos” (parágrafos) passarem:

```python
# backend/prompts.py
PROMPT_EXTRACAO_FATO_GERADOR_V1 = """
...
**REGRAS:**
- fato_gerador_padronizado: Uma única frase de até 15 palavras com ENTIDADE + AÇÃO (ex.: "Banco Master sofre liquidação pelo BC", ...).
- Se o artigo relatar múltiplos eventos independentes da mesma empresa, extraia APENAS o facto com maior impacto na liquidez/solvabilidade/governança ...
...
"""
```

---

## 4. Modelo de contrato (`backend/models.py`) — FatoGeradorContract

O Pydantic não impõe “15 palavras”; só `max_length=300`, o que permite frases longas e prejudica o agrupamento por Entidade + Ação:

```python
# backend/models.py, linhas 80-93
class FatoGeradorContract(BaseModel):
    fato_gerador_padronizado: str = Field(
        ...,
        min_length=1,
        max_length=300,   # <-- permite ~50+ palavras; prompt diz "até 15 palavras"
        description="Frase curta (até ~15 palavras) que descreve o fato central: entidade + ação."
    )
    entidade_primaria: Optional[str] = Field(default=None, max_length=200)
    verbo_acao_financeira: Optional[str] = Field(default=None, max_length=100)
    valor_envolvido: Optional[str] = Field(default=None, max_length=100)
```

**Correção sugerida:** Reduzir `max_length` (ex.: 120–150 caracteres) e/ou adicionar validação por número de palavras (ex.: `len(fato_gerador_padronizado.split()) <= 15`).

---

## 5. Resumo das correções cirúrgicas sugeridas

| Problema | Onde | Ação sugerida |
|--------|------|----------------|
| Buraco Negro (157 artigos em "Outras notícias") | `BATCH_SIZE_AGRUPAMENTO` + fallback | Reduzir lote (ex.: 50–80); no fallback, rejeitar tema genérico e grupos com >10 ids (ou não criar cluster e marcar lote para retry). |
| Fallback destrói precisão | `extrair_grupos_agrupamento_seguro` + uso em `agrupar_noticias_com_prompt` | Se veio do fallback: não aceitar `tema_principal` em lista bloqueada ("Outras notícias", "Diversos", ...); não aceitar `len(ids_originais) > 10`; ou tratar como falha e não criar clusters. |
| Silo tipo_fonte na Etapa 4 | `consolidacao_final_clusters` | Rever “Lei Imutável”: permitir merge internacional + brasil_* quando for o mesmo evento (ex.: mesmo título/fato_gerador ou similaridade acima de threshold). |
| Higienização fraca | PROMPT_HIGIENIZACAO_V1 + chamada LLM | Exemplificar “receitas culinárias” de forma explícita; garantir temperature=0 na Etapa 1.5. |
| Fato gerador prosaico | FatoGeradorContract + prompt | Reduzir `max_length` (ex.: 120); opcional: validação `<= 15 palavras`. |

Este ficheiro pode ser usado como referência única para aplicar as correções no código.
