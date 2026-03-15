# TELEGRAM_LISTENER — Coleta de PDFs via Grupos Telegram

Subprojeto que escuta grupos e canais do Telegram usando sua conta de usuário (não bot), baixa PDFs de jornais automaticamente e dispara o processamento do pipeline principal (AlphaFeed).

## Visão Geral

| Componente | Descrição |
|------------|-----------|
| **agent.py** | Lógica principal: conexão Telethon, detecção de documentos, download, deduplicação |
| **config.py** | Padrões de jornais, configurações, caminhos |
| **run.py** | Ponto de entrada CLI |

## Requisitos

```bash
pip install telethon python-dotenv
```

Credenciais em https://my.telegram.org (API ID + API Hash).

## Variáveis de Ambiente

Configure em `backend/.env` ou `.env`:

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `TELEGRAM_API_ID` | API ID do Telegram | `12345678` |
| `TELEGRAM_API_HASH` | API Hash | `abc123...` |
| `TELEGRAM_PHONE` | Telefone internacional | `+5511999999999` |
| `TELEGRAM_LISTEN_CHATS` | IDs dos chats (separados por vírgula) | `-1001234567890,-1009876543210` |

## Uso

Execute **a partir da raiz do projeto**:

```bash
# Escuta em tempo real (Ctrl+C para parar)
python -m TELEGRAM_LISTENER

# Backfill: baixa PDFs das últimas 24h e encerra
python -m TELEGRAM_LISTENER --backfill

# Sem disparar processamento (apenas download)
python -m TELEGRAM_LISTENER --no-process
```

## Integração com o Pipeline Principal

1. PDFs são salvos em `../pdfs/` (mesma pasta usada por `load_news.py`)
2. Após cada download (tempo real) ou ao fim do backfill, o listener chama `load_news.py` do projeto principal
3. O `load_news.py` ingere os PDFs no banco e move para `../pdfs/processados/`

Fluxo: **Telegram → Download → load_news** (ingestão). O processamento (`process_articles`) pode ser disparado separadamente via `run_complete_workflow.py` ou job agendado.

## Padrões de Jornais

O listener considera documentos como “jornal de interesse” se o nome ou o texto da mensagem contiver:

- Valor, Folha, Estadão, Gazeta, Correio Braziliense, O Globo
- Broadcast, InfoMoney, Capital Aberto, Brazil Journal
- Pipeline, Reset, Neofeed, Bloomberg, Reuters, Financial Times
- Ou se o arquivo terminar em `.pdf`

Edite `config.py` para personalizar.

## Segurança

- **Sessão Telethon** (` .telegram_session*`) contém tokens do usuário — nunca commitar
- Já está no `.gitignore` do projeto
- Use conta dedicada se preferir isolar do uso pessoal

## Obter IDs dos Grupos

1. Adicione o bot [@userinfobot](https://t.me/userinfobot) ao grupo (ou use outro método)
2. O ID do grupo/canal costuma ser algo como `-1001234567890`
3. Coloque em `TELEGRAM_LISTEN_CHATS` separado por vírgula
