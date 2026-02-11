# ESPECIFICAÇÃO TÉCNICA: MÓDULO DE DISSEMINAÇÃO TELEGRAM

**Status:** Implementado
**Objetivo:** Automatizar o envio de um Morning Call/Daily Briefing sintetizado para canais do Telegram após o processamento do dia.
**Dependências:** Pipeline v1 (Clusters Processados) e `backend/prompts.py`.

---

## 1. Visão Geral da Arquitetura

O módulo funcionará como o passo final do fluxo de trabalho. Ele não altera dados, apenas consome a inteligência gerada (Clusters P1/P2) e a transforma em um formato de consumo rápido (Mobile/Chat).

### Componentes Envolvidos:

| Componente | Arquivo | Papel |
|---|---|---|
| Gerador de Conteúdo | `backend/broadcaster.py` | Lê clusters do dia, seleciona relevantes, invoca LLM para formatação |
| Prompt Especialista | `backend/prompts.py` | `PROMPT_TELEGRAM_BRIEFING_V1` — brevidade, HTML para Telegram, emojis |
| Cliente Telegram | Dentro de `broadcaster.py` | `requests.post` para API do Telegram (sem dependência pesada) |
| Orquestrador | `run_complete_workflow.py` | ETAPA 5 (pós-migração) |
| CLI Standalone | `send_telegram.py` | Script para envio manual/teste |

---

## 2. Configuração de Ambiente (.env)

```
TELEGRAM_BOT_TOKEN=<token do @BotFather>
TELEGRAM_CHAT_ID=<ID do canal/grupo, ex: -100xxxxxx>
```

O módulo é **silenciosamente desabilitado** se as variáveis não estiverem configuradas.

---

## 3. Fluxo Lógico

```
1. Query: clusters_eventos WHERE data=hoje AND status='ativo' AND prioridade IN (P1, P2)
2. Preparação: [{titulo, prioridade, resumo_cluster, tag}] → JSON simplificado
3. LLM: Gemini Flash + PROMPT_TELEGRAM_BRIEFING_V1 → texto HTML formatado
4. Split: Quebra mensagem em partes de ≤4000 chars (respeita \n\n)
5. Envio: POST https://api.telegram.org/bot<TOKEN>/sendMessage (parse_mode=HTML)
6. Idempotência: Verifica log do dia antes de enviar (evita spam)
7. Auditoria: Registra em logs_processamento
```

---

## 4. Estrutura do Briefing

```
🚨 RESUMO DO DIA - DD/MM/AAAA

📌 MANCHETE DO DIA
[Resumo do evento P1 mais importante]

📊 DESTAQUES
• [P1] Título - resumo 1 linha
• [P2] Título - resumo 1 linha
...

🏢 RADAR CORPORATIVO
• Empresa X: resultado + M&A
...

⚖️ JURÍDICO / REGULATÓRIO
• ...

🕐 Gerado pelo AlphaFeed v2 às HH:MM
```

---

## 5. Restrições Técnicas

- **Limite Telegram:** 4096 caracteres por mensagem → splitter obrigatório
- **Formatação:** HTML (`<b>`, `<i>`, `<a>`) — mais estável que Markdown no Telegram
- **Dependência:** Apenas `requests` (stdlib-like, sem python-telegram-bot)
- **Segurança:** Token nunca hardcoded; abort silencioso se ausente
- **Idempotência:** Verifica `logs_processamento` do dia antes de enviar

---

## 6. Integração no Pipeline

```
run_complete_workflow.py
  ETAPA 1: load_news.py (ingestão)
  ETAPA 2: process_articles.py (processamento + Graph-RAG v2)
  ETAPA 3: migrate_incremental.py (sync Heroku)
  ETAPA 4: [reservada]
  ETAPA 5: send_telegram.py (briefing diário) ← NOVO
```

**Condição:** Só executa se `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` existirem no ambiente.
**Falha:** Logada mas NÃO interrompe o pipeline.
