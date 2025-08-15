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
  - Promoções de carros até 200 mil (heurística por palavras-chave + síntese opcional por LLM).
  - Impactos P1/P2/P3 na relação EUA × Rússia (filtragem por prioridade e palavras-chave + síntese por LLM).
  - Busca genérica por palavras-chave em título/resumo (acentos tolerados, stopwords simples) com amostragem e síntese por LLM.
- **KB carregado** automaticamente para orientar o LLM (se a variável `GEMINI_API_KEY` estiver configurada).
- **Logs detalhados** de execução: abertura de sessão, paginação, contagens, início/fim de síntese.
- **Endpoints FastAPI** (em `backend/main.py`):
  - `POST /api/estagiario/start` — inicia sessão de chat do dia.
  - `POST /api/estagiario/send` — envia pergunta e retorna resposta do agente (persistindo conversa).
  - `GET /api/estagiario/messages/{session_id}` — histórico de mensagens.

### Fluxo de resposta atual (alto nível)
1) Normaliza pergunta e detecta o caso (irrelevantes, carros, EUA×Rússia, genérico).
2) Carrega clusters do dia com paginação (prioridade-alvo ou ALL).
3) Filtra por palavras-chave (e/ou prioridade) e monta uma amostra de itens relevantes.
4) Opcional: chama o LLM (Gemini) com a KB + amostra curta para sintetizar uma resposta estruturada.
5) Fallbacks: lista curta em texto ou métricas do dia quando insuficiente.

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
- **Modo foco**: ao clicar no card, expandir para ocupar ~70% da tela (como modal) e voltar ao estado encaixado ao fechar.
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

## Observações
- O agente prioriza respostas concisas. Para investigações mais profundas, ele segue o plano A (ranquear → aprofundar → sintetizar) antes de redigir.
- O uso do LLM é orientado pela KB e por amostras curtas para manter custo e latência sob controle.

