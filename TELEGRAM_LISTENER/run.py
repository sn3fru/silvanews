#!/usr/bin/env python3
"""
Ponto de entrada do Telegram Listener — escuta grupos e baixa PDFs.

Uso:
    python -m TELEGRAM_LISTENER              # escuta em tempo real
    python -m TELEGRAM_LISTENER --backfill  # baixa PDFs das ultimas 24h e sai
    python -m TELEGRAM_LISTENER --no-process  # nao chama load_news apos download

Ou, a partir da pasta TELEGRAM_LISTENER:
    python run.py
    python run.py --backfill
"""

import sys
import asyncio
from pathlib import Path

# Garante que o projeto raiz esteja no path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def main():
    backfill = "--backfill" in sys.argv
    no_process = "--no-process" in sys.argv

    try:
        from TELEGRAM_LISTENER.agent import run_listener
        asyncio.run(run_listener(backfill=backfill, trigger_process=not no_process))
    except KeyboardInterrupt:
        print("\n[OK] Listener encerrado.")
    except ImportError as e:
        print(f"[ERRO] {e}")
        print("  Execute a partir da raiz do projeto: python -m TELEGRAM_LISTENER")
        sys.exit(1)


if __name__ == "__main__":
    main()
