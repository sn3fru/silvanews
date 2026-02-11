#!/usr/bin/env python3
"""
CLI wrapper para envio do Daily Briefing via Telegram.

Uso:
    python send_telegram.py              # Envia briefing do dia
    python send_telegram.py --dry-run    # Gera sem enviar (preview)
    python send_telegram.py --force      # Reenvia mesmo se já enviou hoje
    python send_telegram.py --day 2026-02-10  # Briefing de data específica

Requer:
    TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no backend/.env

Spec completa: docs/TELEGRAM_MODULE_SPEC.md
"""

import sys
import os
import argparse
from pathlib import Path

# Setup paths
project_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(project_dir))

# Carrega .env
from dotenv import load_dotenv
load_dotenv(project_dir / "backend" / ".env")


def main():
    parser = argparse.ArgumentParser(
        description="BTG AlphaFeed - Telegram Daily Briefing",
        epilog="Spec: docs/TELEGRAM_MODULE_SPEC.md",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Gera briefing e mostra no terminal (nao envia)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Reenvia mesmo se ja enviou hoje",
    )
    parser.add_argument(
        "--day", type=str, default=None,
        help="Data do briefing (YYYY-MM-DD). Default: hoje",
    )
    args = parser.parse_args()

    from backend.broadcaster import TelegramBroadcaster

    broadcaster = TelegramBroadcaster()

    if not args.dry_run and not broadcaster.is_configured:
        print("❌ Telegram não configurado.")
        print("   Adicione ao backend/.env:")
        print("   TELEGRAM_BOT_TOKEN=seu_token_aqui")
        print("   TELEGRAM_CHAT_ID=seu_chat_id_aqui")
        print("")
        print("   Para apenas visualizar o briefing: python send_telegram.py --dry-run")
        sys.exit(1)

    ok = broadcaster.run(
        day_str=args.day,
        dry_run=args.dry_run,
        force=args.force,
    )

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
