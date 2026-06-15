#!/usr/bin/env python3
"""
Sobe as exportacoes diarias (.md) para o Google Drive usando OAuth (conta pessoal).

POR QUE OAUTH E NAO SERVICE ACCOUNT:
  Service accounts NAO tem cota de armazenamento no Drive pessoal (Gmail).
  Qualquer upload retorna 403 storageQuotaExceeded. A unica forma de subir
  arquivos numa pasta de conta Gmail e autenticar como um usuario real (OAuth),
  cujos arquivos contam contra a cota pessoal (15GB) dele.

SETUP (uma vez, na SUA conta Google — nao precisa do dono do projeto):
  1. https://console.cloud.google.com -> criar projeto (ou usar um existente seu)
  2. APIs e Servicos -> Ativar "Google Drive API"
  3. Tela de consentimento OAuth -> tipo "Externo" -> adicionar seu email como usuario de teste
  4. Credenciais -> Criar credencial -> ID do cliente OAuth -> tipo "App para computador"
  5. Baixar o JSON e salvar em: backend/google_oauth_client.json
  6. pip install google-auth-oauthlib google-api-python-client

PRIMEIRA EXECUCAO:
  Abre o navegador para voce autorizar com marcosviniciusenator@gmail.com.
  O token fica salvo em backend/google_oauth_token.json (renova sozinho depois).

Uso:
  python scripts/upload_to_drive.py --check
  python scripts/upload_to_drive.py --date 2026-06-09
  python scripts/upload_to_drive.py --days 14
  python scripts/upload_to_drive.py --days 14 --replace   # sobrescreve existentes
"""

from __future__ import annotations

import argparse
import io
import mimetypes
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

# drive.file so enxerga pastas ja compartilhadas; precisa de acesso amplo para a pasta do Roger
SCOPES = ["https://www.googleapis.com/auth/drive"]
EXPORT_ROOT = ROOT.parent / "exportacoes_diarias"

CLIENT_SECRET = ROOT / "backend" / "google_oauth_client.json"
TOKEN_PATH = ROOT / "backend" / "google_oauth_token.json"

# Pasta raiz no Drive (compartilhada pelo dono). Pode sobrescrever via env.
REPO_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_REPO_NAME", "_SILVA-NEWS - Repositório")
REPO_FOLDER_ID = os.getenv("GOOGLE_DRIVE_REPO_ID", "1QZZMnGUgY5E0fR0c4Shd_crBxzdlu5ts")


def build_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit(
            "Dependencias faltando. Instale com:\n"
            "  pip install google-auth-oauthlib google-api-python-client"
        ) from exc

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                raise SystemExit(
                    f"OAuth client nao encontrado: {CLIENT_SECRET}\n\n"
                    "Crie um 'ID do cliente OAuth' tipo 'App para computador' na sua\n"
                    "conta Google, baixe o JSON e salve nesse caminho.\n"
                    "(passo a passo no topo deste arquivo)"
                )
            print("Abrindo navegador para autorizar (use a conta com acesso ao Drive)...", flush=True)
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        print(f"Token salvo em {TOKEN_PATH}")

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def check_connection(service) -> None:
    about = service.about().get(fields="user,storageQuota").execute()
    user = about.get("user", {})
    quota = about.get("storageQuota", {})
    print("Conexao OK (OAuth)")
    print(f"  Conta: {user.get('emailAddress', 'N/A')}")
    usage = int(quota.get("usage", 0))
    limit = quota.get("limit")
    print(f"  Uso: {usage / 1e9:.2f} GB" + (f" de {int(limit) / 1e9:.0f} GB" if limit else ""))


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_folder(service, name: str, parent_id: Optional[str]) -> Optional[str]:
    q = (
        "mimeType='application/vnd.google-apps.folder' and trashed=false "
        f"and name='{_escape_query(name)}'"
    )
    if parent_id:
        q += f" and '{parent_id}' in parents"
    result = service.files().list(
        q=q, fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def get_or_create_folder(service, name: str, parent_id: Optional[str]) -> str:
    existing = find_folder(service, name, parent_id)
    if existing:
        return existing
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    created = service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return created["id"]


def resolve_repo_folder(service) -> str:
    """Retorna o ID da pasta raiz do repositorio no Drive."""
    if REPO_FOLDER_ID:
        try:
            info = service.files().get(
                fileId=REPO_FOLDER_ID, fields="id,name", supportsAllDrives=True
            ).execute()
            return info["id"]
        except Exception:
            pass
    found = find_folder(service, REPO_FOLDER_NAME, None)
    if found:
        return found
    raise SystemExit(
        f"Pasta raiz '{REPO_FOLDER_NAME}' nao encontrada no Drive.\n"
        "Confirme que ela esta compartilhada com a sua conta."
    )


def find_file_in_folder(service, name: str, folder_id: str) -> Optional[str]:
    q = f"name='{_escape_query(name)}' and '{folder_id}' in parents and trashed=false"
    result = service.files().list(
        q=q, fields="files(id,name)", supportsAllDrives=True, includeItemsFromAllDrives=True
    ).execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def upload_md(service, local_path: Path, folder_id: str, replace: bool) -> str:
    from googleapiclient.http import MediaIoBaseUpload

    existing_id = find_file_in_folder(service, local_path.name, folder_id)
    if existing_id:
        if not replace:
            return "skip"
        try:
            service.files().delete(fileId=existing_id, supportsAllDrives=True).execute()
        except Exception:
            pass

    mime = mimetypes.guess_type(local_path.name)[0] or "text/markdown"
    media = MediaIoBaseUpload(io.BytesIO(local_path.read_bytes()), mimetype=mime, resumable=False)
    meta = {"name": local_path.name, "parents": [folder_id]}
    service.files().create(body=meta, media_body=media, fields="id", supportsAllDrives=True).execute()
    return "update" if existing_id else "create"


def upload_day(service, repo_id: str, target_date: date, replace: bool) -> dict:
    day_name = target_date.strftime("%Y-%m-%d")
    day_dir = EXPORT_ROOT / day_name
    if not day_dir.exists():
        print(f"  [{day_name}] pasta local inexistente, skip")
        return {}

    day_folder_id = get_or_create_folder(service, day_name, repo_id)
    stats = {"create": 0, "update": 0, "skip": 0}

    # Upload .md from root (legacy) and from subfolders (clusters/, artigos/)
    subdirs = [day_dir]
    for sub in sorted(day_dir.iterdir()):
        if sub.is_dir():
            subdirs.append(sub)

    for folder_path in subdirs:
        md_files = sorted(folder_path.glob("*.md"))
        if not md_files:
            continue

        if folder_path == day_dir:
            target_folder_id = day_folder_id
        else:
            target_folder_id = get_or_create_folder(service, folder_path.name, day_folder_id)

        for md in md_files:
            action = upload_md(service, md, target_folder_id, replace)
            stats[action] = stats.get(action, 0) + 1

    total_files = stats["create"] + stats["update"] + stats["skip"]
    print(
        f"  [{day_name}] {total_files} arquivos — "
        f"{stats['create']} novos, {stats['update']} atualizados, {stats['skip']} ja existiam"
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Sobe exportacoes .md para o Google Drive (OAuth)")
    parser.add_argument("--check", action="store_true", help="So testa autenticacao")
    parser.add_argument("--date", type=str, help="Data especifica (YYYY-MM-DD)")
    parser.add_argument("--days", type=int, default=1, help="Dias retroativos (default: 1 = hoje)")
    parser.add_argument("--replace", action="store_true", help="Sobrescreve arquivos ja existentes")
    args = parser.parse_args()

    service = build_service()
    check_connection(service)

    if args.check:
        repo_id = resolve_repo_folder(service)
        print(f"Pasta raiz OK: {REPO_FOLDER_NAME} (id={repo_id})")
        return

    if args.date:
        dates = [datetime.strptime(args.date, "%Y-%m-%d").date()]
    else:
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(args.days)]

    repo_id = resolve_repo_folder(service)
    print(f"Subindo para: {REPO_FOLDER_NAME} (id={repo_id})")

    total = {"create": 0, "update": 0, "skip": 0}
    for d in sorted(dates):
        stats = upload_day(service, repo_id, d, args.replace)
        for k, v in stats.items():
            total[k] = total.get(k, 0) + v

    print(
        f"\nTotal: {total['create']} novos, "
        f"{total['update']} atualizados, {total['skip']} ja existiam."
    )


if __name__ == "__main__":
    main()
