## Agente "Estagiário" (em construção) 🚧

O Estagiário é um agente que responde perguntas sobre TODAS as notícias de um dia, consultando o banco de dados e selecionando apenas o que é útil por prioridade e tag, sem alterar o pipeline atual.

### O que já está implementado
- **Arquitetura desacoplada**: pasta `agents/estagiario/` com lógica própria e KB em `knowledge/KB_SITE.md`.
- **Integração com backend** (reuso de CRUDs existentes):
  - `get_clusters_for_feed_by_date` para paginação de clusters do dia.
  - `get_cluster_details_by_id` para abrir detalhes de um cluster (para respostas mais ricas; usado conforme evoluirmos o plano).
  - `get_metricas_by_date` para fallback informativo.
- **Casos suportados no agente** (`EstagiarioAgent.answer`):
  - Contagem de itens irrelevantes do dia (consulta precisa por ORM).
  - Promoções de carros (com/sem preço explícito, sem default oculto de valor), com triagem e síntese.
  - Impactos P1/P2/P3 na relação EUA × Rússia com fluxo resiliente (multi-estratégia, ver abaixo).
  - Busca genérica (intent → filtros → ranking → aprofundar → síntese em Markdown) com KB.
  - Edições seguras no banco (unitárias): atualizar prioridade, trocar tag, merge 1→1 de clusters (guardrails abaixo).
- **KB carregado** automaticamente para orientar o LLM (se a variável `GEMINI_API_KEY` estiver configurada).
- **Logs detalhados** de execução: abertura de sessão, paginação, contagens, início/fim de síntese.
- **Endpoints FastAPI** (em `backend/main.py`):
  - `POST /api/estagiario/start` — inicia sessão de chat do dia.
  - `POST /api/estagiario/send` — envia pergunta e retorna resposta do agente (persistindo conversa).
  - `GET /api/estagiario/messages/{session_id}` — histórico de mensagens.

### Arquitetura do agente (alto nível)
1) Interpretação da intenção: normaliza pergunta; extrai prioridades explícitas (P1/P2/P3), termos e pistas de tags; data padrão: hoje.
2) Coleta inicial: pagina clusters do dia por prioridades inferidas (ou ALL).
3) Pré-filtragem leve: heurística lexical temática (evita perder recall) e, quando necessário, leve filtro por keywords apenas em conjuntos muito grandes.
4) Triagem semântica (LLM): recebe amostra priorizada e retorna 10–15 IDs mais promissores para a tarefa.
5) Aprofundar top-K: carrega detalhes e fontes; se a tarefa exigir síntese, tenta:
   - 5.1) Síntese com resumos/títulos; se insuficiente,
   - 5.2) Síntese a partir de textos brutos (artigos raw) com amostra limitada.
6) Resposta final: em Markdown, direta e executiva, com seção “Notícias pesquisadas” numerada (ID, Título, URL, Jornal).
7) Guardrails: nunca descreve etapas/tools no output; não pede dados adicionais por padrão; busca sempre “chegar no objetivo”.

### Uso programático
```python
from agents.estagiario.agent import EstagiarioAgent
agent = EstagiarioAgent()

# Exemplo 1: contagem de irrelevantes
ans = agent.answer("liste quantas noticias classificamos como irrelevantes")
print(ans.text, ans.data)

# Exemplo 2: impactos P1 EUA × Rússia
ans = agent.answer("Resuma os principais Impactos das noticias de prioridade p1 para a relacao EUA x Russia")
print(ans.text)
```

### Uso via API
- `POST /api/estagiario/start`
  - body: `{ "date": "YYYY-MM-DD" }`
  - resp: `{ "session_id": number }`
- `POST /api/estagiario/send`
  - body: `{ "session_id": number, "message": string, "date": "YYYY-MM-DD" }`
  - resp: `{ "ok": bool, "text": string, "data": object }`
- `GET /api/estagiario/messages/{session_id}`
  - resp: `[{ id, role, content, timestamp }, ...]`

### Dependências e configuração
- Opcional LLM (Gemini): exporte `GEMINI_API_KEY` para habilitar a síntese.
- Reuso de modelos/CRUDs do backend existentes; sem migrações adicionais para o core do pipeline.
- **Base de Conhecimento Atualizada**: O agente agora consulta automaticamente as tags e prioridades configuradas no banco de dados via `backend/prompts.py`, que carrega dinamicamente do PostgreSQL.
- **Configuração Transparente**: As estruturas `TAGS_SPECIAL_SITUATIONS`, `P1_ITENS`, `P2_ITENS` e `P3_ITENS` são mantidas para compatibilidade, mas agora são populadas do banco de dados.

## Plano de evolução (próximos passos)

### A. Pipeline de “pensar antes de responder” (operacional)
- **Planejamento explícito por etapas** para toda pergunta genérica:
  1) Entender intenção → extrair keywords, prioridades e tags candidatas.
  2) Buscar clusters do dia por prioridade/tag.
  3) **Ranquear** por (prioridade, match semântico/lexical no título e no resumo).
  4) **Aprofundar top-K**: abrir detalhes do cluster (ids, fontes). Se promissor, carregar resumos; se ainda promissor, opcionalmente abrir texto completo dos artigos desse cluster.
  5) **Síntese do zero**: redigir resposta estruturada (títulos, bullets, tabela), citando fontes e IDs.
  6) Devolver também um `data.itens` com os principais clusters usados.

### B. UI/UX do card Estagiário
- **Modo foco**: ao clicar no card, expande para ocupar ~90% da tela (modal) e volta ao estado encaixado ao fechar.
- **Renderização Markdown**: permitir títulos, negritos, listas, tabelas e URLs ao exibir `answer.text` do Estagiário.
- **Modal de progresso**: etapas visuais “Entendendo → Planejando → Consultando DB → Sintetizando”, com gif.

### C. Qualidade de Resposta
- **Citações de fontes**: incluir links e nomes das fontes principais por cluster utilizado.
- **Cortes temáticos**: filtros por tag e setor (e.g., energia, autos, macro, geopolítica).
- **Resumos orientados a decisão**: sempre responder em tom executivo e com takeaways acionáveis.

### D. Robustez e performance
- **Batching e caching**: cache por dia/consulta (hash de intenção e filtros) para reuso rápido.
- **Limites e timeouts**: fail-safe ao abrir textos completos (lazy e com teto de K clusters).
- **Telemetria**: medir recall/precisão, tempo por etapa, taxa de fallback LLM.

### E. Escopo ampliado
- **Análise multi-dia**: permitir perguntas que cruzem janelas de datas.
- **Consultas por tags personalizadas**: suporte a nomes de tags frequentes do pipeline.
- **Ferramentas explícitas**: formalizar “tools” internas (e.g., `db_query`, `fetch_clusters`, `expand_cluster`) com contratos claros.

## Edições seguras no banco (capacidade do Estagiário)
- Sempre unitárias; nunca em lote; nunca dropar tabelas; nunca deletar mais de um item por comando.
- Prioridades permitidas: `P1_CRITICO`, `P2_ESTRATEGICO`, `P3_MONITORAMENTO`, `IRRELEVANTE`.
- Tags permitidas: catálogo configurável via frontend em `/frontend/settings.html` → aba "Prompts" → "Tags" (persistidas no PostgreSQL).
- Exemplos de comandos aceitos:
  - Atualizar prioridade: "atualize prioridade do cluster 123 para p2"
  - Atualizar tag: "troque a tag do cluster 456 para Internacional"

## Observações
- O agente prioriza respostas concisas. Para investigações mais profundas, ele segue o plano A (ranquear → aprofundar → sintetizar) antes de redigir.
- O uso do LLM é orientado pela KB e por amostras curtas para manter custo e latência sob controle.

