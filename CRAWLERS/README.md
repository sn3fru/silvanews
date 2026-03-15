# CRAWLERS — Coleta Automatizada de Noticias Online

Subprojeto que faz login e download de noticias de sites especializados.

## Fontes Ativas

| Site | Script | Output |
|------|--------|--------|
| Valor Economico | `src/ValorEconomico/src/1_main_paginated.py` | `output/noticias_valor_paginated.json` |
| Jota | `src/Jota/src/1_main_paginated.py` | `output/noticias_jota_paginated.json` |
| Conjur | `src/Conjur/main_conjur.py` | `output/noticias_conjur_ultimas_24h.json` |
| Brazil Journal | `src/BrazilJournal/main_brazil_journal.py` | `output/noticias_brazil_journal_ultimas_24h.json` |
| Migalhas | `src/Migalhas/src/1_main_paginated.py` | `output/noticias_migalhas_paginated.json` |

## Como Funciona

```bash
cd CRAWLERS/src
python news_manager.py
```

1. Limpa a pasta `output/`
2. Roda cada crawler sequencialmente (com 5s de intervalo)
3. Cada crawler faz login no site, coleta noticias recentes e salva JSON em `output/`
4. Ao final, `gerar_dump_global()` consolida todos os JSONs em um unico arquivo:
   `dump/dump_crawlers_YYYYMMDD.json`

## Integracao com o Pipeline

O `run_complete_workflow.py` chama `run_crawlers()` como **ETAPA 0.5** (antes do load_news):
1. Roda `news_manager.py` via subprocess
2. Copia o `dump_crawlers_YYYYMMDD.json` para a pasta `../pdfs/`
3. O `load_news.py` (ETAPA 1) processa o JSON junto com os PDFs

## Credenciais

Cada crawler precisa de `credentials.json` e/ou `data/cookies.txt` na sua pasta.
Esses arquivos NAO devem ser commitados (contem senhas).

## Output Format

Cada JSON contem uma lista de objetos:
```json
[
  {
    "titulo": "...",
    "texto_bruto": "...",
    "url_original": "https://...",
    "jornal": "Valor Econômico",
    "data_publicacao": "2026-03-15T10:30:00"
  }
]
```
