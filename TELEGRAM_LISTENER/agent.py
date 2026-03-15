# TELEGRAM_LISTENER/agent.py
"""Agente que escuta grupos Telegram e baixa PDFs."""

import os
import sys
import hashlib
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone

from .config import PDFS_DIR, is_journal, safe_filename


def _load_env():
    """Carrega variáveis de ambiente do backend/.env ou .env."""
    try:
        from dotenv import load_dotenv
        project_root = Path(__file__).resolve().parent.parent
        for candidate in [
            project_root / "backend" / ".env",
            project_root / ".env",
            Path.cwd() / "backend" / ".env",
            Path.cwd() / ".env",
        ]:
            if candidate.exists():
                load_dotenv(str(candidate), override=False)
                break
    except ImportError:
        pass


def _file_hash(filepath: Path) -> str:
    """Hash curto do arquivo para deduplicação."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _trigger_load_news(pdfs_dir: Path, project_root: Path) -> bool:
    """
    Chama o load_news.py do projeto principal para processar os PDFs.
    Executa em subprocess para isolar o ambiente e garantir que usa o mesmo fluxo do pipeline.
    """
    try:
        from dotenv import dotenv_values
        env_file = project_root / "backend" / ".env"
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        if os.name == "nt":
            env["PYTHONLEGACYWINDOWSSTDIO"] = "utf-8"
        if env_file.exists():
            for k, v in (dotenv_values(env_file) or {}).items():
                if v and not env.get(k):
                    env[k] = v

        result = subprocess.run(
            [
                sys.executable,
                "load_news.py",
                "--dir",
                str(pdfs_dir),
                "--direct",
                "--yes",
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

        if result.returncode == 0:
            print("[OK] load_news concluído. PDFs processados e movidos para processados/")
            return True
        else:
            print(f"[AVISO] load_news retornou {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    print(f"  {line}")
            return False
    except Exception as e:
        print(f"[ERRO] Falha ao chamar load_news: {e}")
        return False


async def run_listener(
    backfill: bool = False,
    trigger_process: bool = True,
):
    """
    Executa o listener em tempo real ou modo backfill.

    Args:
        backfill: Se True, baixa PDFs das últimas 24h e sai.
        trigger_process: Se True, após downloads aciona load_news do projeto principal.
    """
    _load_env()

    try:
        from telethon import TelegramClient, events
    except ImportError:
        print("[ERRO] Telethon não instalado. Execute: pip install telethon")
        sys.exit(1)

    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE")
    chats_raw = os.getenv("TELEGRAM_LISTEN_CHATS", "")

    if not api_id or not api_hash:
        print("[ERRO] TELEGRAM_API_ID e TELEGRAM_API_HASH são obrigatórios.")
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

    project_root = Path(__file__).resolve().parent.parent
    PDFS_DIR.mkdir(parents=True, exist_ok=True)

    session_path = project_root / "TELEGRAM_LISTENER" / ".telegram_session"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(session_path), api_id, api_hash)

    await client.start(phone=phone)
    me = await client.get_me()
    print(f"[OK] Logado como: {me.first_name} (@{me.username})")
    print(f"[OK] Pasta de download: {PDFS_DIR}")
    if chats:
        print(f"[OK] Monitorando chats: {chats}")
    if trigger_process:
        print("[OK] Processamento automático: ativado (load_news após downloads)")

    downloaded_hashes = set()
    downloaded_count = 0

    async def _download_document(message, chat_name=""):
        nonlocal downloaded_count
        if not message.document:
            return

        attrs = message.document.attributes
        filename = None
        for attr in attrs:
            if hasattr(attr, "file_name"):
                filename = attr.file_name
                break

        if not filename:
            mime = message.document.mime_type or ""
            if "pdf" in mime:
                filename = f"telegram_{message.id}.pdf"
            else:
                return

        msg_text = message.text or message.message or ""
        if not is_journal(filename, msg_text):
            return

        safe_name = safe_filename(filename)
        dest = PDFS_DIR / safe_name

        if dest.exists():
            print(f"  [SKIP] Já existe: {safe_name}")
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
            downloaded_count += 1
            print(f"  [OK] Salvo: {dest}")

        except Exception as e:
            print(f"  [ERRO] Falha ao baixar {safe_name}: {e}")
            if dest.exists():
                dest.unlink()

    # --- Modo backfill ---
    if backfill:
        print("\n[BACKFILL] Buscando documentos das últimas 24h...")
        since = datetime.now(timezone.utc) - timedelta(hours=24)

        targets = chats if chats else []
        if not targets:
            async for dialog in client.iter_dialogs(limit=50):
                targets.append(dialog.id)

        total = 0
        for chat_id in targets:
            try:
                entity = await client.get_entity(chat_id)
                chat_name = getattr(entity, "title", str(chat_id))
                async for msg in client.iter_messages(entity, offset_date=since, reverse=True):
                    if msg.document:
                        await _download_document(msg, chat_name)
                        total += 1
            except Exception as e:
                print(f"  [AVISO] Não consegui acessar chat {chat_id}: {e}")

        print(f"[BACKFILL] Concluído. {total} documentos verificados, {downloaded_count} novos baixados.")
        await client.disconnect()

        if trigger_process and downloaded_count > 0:
            print("\n[PROCESS] Acionando load_news do projeto principal...")
            _trigger_load_news(PDFS_DIR, project_root)
        return

    # --- Modo real-time ---
    @client.on(events.NewMessage(chats=chats or None))
    async def handler(event):
        nonlocal downloaded_count
        if not event.message.document:
            return
        chat = await event.get_chat()
        chat_name = getattr(chat, "title", str(chat.id))
        await _download_document(event.message, chat_name)
        if trigger_process and downloaded_count > 0:
            print("\n[PROCESS] Novo PDF baixado. Acionando load_news...")
            if _trigger_load_news(PDFS_DIR, project_root):
                downloaded_count = 0  # reset após processar

    print("\n[LISTENER] Escutando mensagens em tempo real... (Ctrl+C para parar)")
    await client.run_until_disconnected()
