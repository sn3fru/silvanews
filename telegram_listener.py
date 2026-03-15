#!/usr/bin/env python3
"""
Telegram Listener — escuta grupos/canais e baixa jornais automaticamente.

Usa Telethon (user account, nao bot). Nao precisa de admin no grupo.

Requisitos:
    pip install telethon
    Obter api_id + api_hash em https://my.telegram.org

Variaveis de ambiente (backend/.env ou .env):
    TELEGRAM_API_ID=12345678
    TELEGRAM_API_HASH=abc123...
    TELEGRAM_PHONE=+5511999999999
    TELEGRAM_LISTEN_CHATS=-1001234567890,-1009876543210  (IDs dos chats separados por virgula)

Uso:
    python telegram_listener.py              # escuta em tempo real
    python telegram_listener.py --backfill   # baixa PDFs das ultimas 24h e sai
"""

import os
import sys
import re
import asyncio
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone


def _load_env():
    try:
        from dotenv import load_dotenv
        for candidate in [
            Path(__file__).parent / "backend" / ".env",
            Path(__file__).parent / ".env",
        ]:
            if candidate.exists():
                load_dotenv(str(candidate), override=False)
    except ImportError:
        pass


_load_env()

PDFS_DIR = Path(__file__).resolve().parent.parent / "pdfs"

JOURNAL_PATTERNS = [
    r"(?i)valor\s*(econ[oô]mico)?",
    r"(?i)folha\s*(de?\s*s\.?\s*paulo)?",
    r"(?i)estado\s*(de?\s*s\.?\s*paulo)?",
    r"(?i)estadao",
    r"(?i)gazeta",
    r"(?i)correio\s*braziliense",
    r"(?i)o\s*globo",
    r"(?i)jornal",
    r"(?i)broadcast",
    r"(?i)infomoney",
    r"(?i)capital\s*aberto",
    r"(?i)brazil\s*journal",
    r"(?i)pipeline",
    r"(?i)reset",
    r"(?i)neofeed",
    r"(?i)bloomberg",
    r"(?i)reuters",
    r"(?i)financial\s*times",
    r"(?i)\.pdf$",
]


def _is_journal(filename: str, message_text: str = "") -> bool:
    """Verifica se o arquivo parece ser um jornal de interesse."""
    combined = f"{filename} {message_text}"
    for pattern in JOURNAL_PATTERNS:
        if re.search(pattern, combined):
            return True
    if filename.lower().endswith(".pdf"):
        return True
    return False


def _safe_filename(name: str) -> str:
    """Normaliza nome do arquivo para salvar."""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip()


def _file_hash(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


async def _run_listener(backfill: bool = False):
    try:
        from telethon import TelegramClient, events
    except ImportError:
        print("[ERRO] Telethon nao instalado. Execute: pip install telethon")
        sys.exit(1)

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")
    chats_raw = os.getenv("TELEGRAM_LISTEN_CHATS", "")

    if not api_id or not api_hash:
        print("[ERRO] TELEGRAM_API_ID e TELEGRAM_API_HASH sao obrigatorios.")
        print("       Obtenha em https://my.telegram.org")
        sys.exit(1)

    api_id = int(api_id)
    chats = []
    for c in chats_raw.split(","):
        c = c.strip()
        if not c:
            continue
        try:
            chats.append(int(c))
        except ValueError:
            chats.append(c)

    if not chats:
        print("[AVISO] TELEGRAM_LISTEN_CHATS vazio. Escutando TODOS os chats (pode ser barulhento).")

    PDFS_DIR.mkdir(parents=True, exist_ok=True)

    session_path = Path(__file__).parent / ".telegram_session"
    client = TelegramClient(str(session_path), api_id, api_hash)

    await client.start(phone=phone)
    me = await client.get_me()
    print(f"[OK] Logado como: {me.first_name} (@{me.username})")
    print(f"[OK] Pasta de download: {PDFS_DIR}")
    if chats:
        print(f"[OK] Monitorando chats: {chats}")

    downloaded_hashes = set()

    async def _download_document(message, chat_name=""):
        """Baixa documento se for jornal de interesse."""
        if not message.document:
            return

        attrs = message.document.attributes
        filename = None
        for attr in attrs:
            if hasattr(attr, 'file_name'):
                filename = attr.file_name
                break

        if not filename:
            mime = message.document.mime_type or ""
            if "pdf" in mime:
                filename = f"telegram_{message.id}.pdf"
            else:
                return

        msg_text = message.text or message.message or ""
        if not _is_journal(filename, msg_text):
            return

        safe_name = _safe_filename(filename)
        dest = PDFS_DIR / safe_name

        if dest.exists():
            print(f"  [SKIP] Ja existe: {safe_name}")
            return

        size_mb = (message.document.size or 0) / (1024 * 1024)
        print(f"  [DOWNLOAD] {safe_name} ({size_mb:.1f} MB) de {chat_name}...")

        try:
            await message.download_media(file=str(dest))

            fhash = _file_hash(dest)
            if fhash in downloaded_hashes:
                dest.unlink()
                print(f"  [DEDUP] Hash duplicado, removido: {safe_name}")
                return

            downloaded_hashes.add(fhash)
            print(f"  [OK] Salvo: {dest}")

        except Exception as e:
            print(f"  [ERRO] Falha ao baixar {safe_name}: {e}")
            if dest.exists():
                dest.unlink()

    # --- Modo backfill: baixa PDFs das ultimas 24h e sai ---
    if backfill:
        print(f"\n[BACKFILL] Buscando documentos das ultimas 24h...")
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        targets = chats if chats else []
        if not targets:
            async for dialog in client.iter_dialogs(limit=50):
                targets.append(dialog.id)

        total = 0
        for chat_id in targets:
            try:
                entity = await client.get_entity(chat_id)
                chat_name = getattr(entity, 'title', str(chat_id))
                async for msg in client.iter_messages(entity, offset_date=since, reverse=True):
                    if msg.document:
                        await _download_document(msg, chat_name)
                        total += 1
            except Exception as e:
                print(f"  [AVISO] Nao consegui acessar chat {chat_id}: {e}")

        print(f"[BACKFILL] Concluido. {total} documentos verificados.")
        await client.disconnect()
        return

    # --- Modo real-time: escuta novas mensagens ---
    @client.on(events.NewMessage(chats=chats or None))
    async def handler(event):
        if not event.message.document:
            return

        chat = await event.get_chat()
        chat_name = getattr(chat, 'title', str(chat.id))
        await _download_document(event.message, chat_name)

    print(f"\n[LISTENER] Escutando mensagens em tempo real... (Ctrl+C para parar)")
    await client.run_until_disconnected()


def main():
    backfill = "--backfill" in sys.argv
    try:
        asyncio.run(_run_listener(backfill=backfill))
    except KeyboardInterrupt:
        print("\n[OK] Listener encerrado.")


if __name__ == "__main__":
    main()
