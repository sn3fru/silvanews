#!/usr/bin/env python3
"""
Testa upload de markdowns para o Google Drive via Service Account.

Pre-requisitos:
  1. pip install google-api-python-client google-auth
  2. Credenciais em backend/google_drive_credentials.json (gitignored)
  3. Pasta no Drive compartilhada com:
     uploader-bot@upload-drive-499020.iam.gserviceaccount.com (Editor)
  4. ID da pasta em GOOGLE_DRIVE_FOLDER_ID ou --folder-id

Uso:
  python scripts/test_google_drive_upload.py --check
  python scripts/test_google_drive_upload.py --folder-id SEU_FOLDER_ID --upload-sample
  python scripts/test_google_drive_upload.py --folder-id SEU_FOLDER_ID --upload-export --date 2026-06-09
"""

from __future__ import annotations

import argparse
import io
import json
import mimetypes
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "backend" / ".env")

SCOPES = ["https://www.googleapis.com/auth/drive"]
EXPORT_ROOT = ROOT.parent / "exportacoes_diarias"
DEFAULT_CREDS = ROOT / "backend" / "google_drive_credentials.json"


def get_credentials_path() -> Path:
    env_path = os.getenv("GOOGLE_DRIVE_CREDENTIALS")
    if env_path:
        return Path(env_path)
    return DEFAULT_CREDS


def build_drive_service(impersonate_email: Optional[str] = None):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit(
            "Dependencias faltando. Instale com:\n"
            "  pip install google-api-python-client google-auth"
        ) from exc

    creds_path = get_credentials_path()
    if not creds_path.exists():
        raise SystemExit(f"Credenciais nao encontradas: {creds_path}")

    creds = service_account.Credentials.from_service_account_file(
        str(creds_path), scopes=SCOPES
    )
    subject = impersonate_email or os.getenv("GOOGLE_DRIVE_IMPERSONATE_EMAIL")
    if subject:
        creds = creds.with_subject(subject)
        print(f"Impersonando: {subject}")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_shared_drives(service, limit: int = 20) -> None:
    result = service.drives().list(pageSize=limit).execute()
    drives = result.get("drives", [])
    print(f"\nShared Drives acessiveis ({len(drives)}):")
    if not drives:
        print("  (nenhum — necessario Google Workspace + Disco compartilhado)")
        return
    for d in drives:
        print(f"  [{d['id']}] {d['name']}")


def get_folder_info(service, folder_id: str) -> dict:
    return (
        service.files()
        .get(
            fileId=folder_id,
            fields="id,name,driveId,owners,shared,mimeType",
            supportsAllDrives=True,
        )
        .execute()
    )


def check_connection(service) -> None:
    about = service.about().get(fields="user,storageQuota").execute()
    user = about.get("user", {})
    quota = about.get("storageQuota", {})
    print("Conexao OK")
    print(f"  Conta: {user.get('emailAddress', 'N/A')}")
    print(f"  Display: {user.get('displayName', 'N/A')}")
    if quota:
        print(f"  Storage usado: {quota.get('usage', 'N/A')} bytes")
        print(f"  Storage limite: {quota.get('limit', 'N/A')}")


def list_shared_folders(service, limit: int = 10) -> None:
    """Lista pastas acessiveis pela service account."""
    query = "mimeType='application/vnd.google-apps.folder' and trashed=false"
    result = (
        service.files()
        .list(
            q=query,
            pageSize=limit,
            fields="files(id, name, owners, shared, createdTime)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    print(f"\nPastas acessiveis ({len(files)}):")
    if not files:
        print("  (nenhuma — compartilhe uma pasta com a service account)")
        return
    for f in files:
        owners = ", ".join(o.get("emailAddress", "?") for o in f.get("owners", []))
        print(f"  [{f['id']}] {f['name']}  (owner: {owners})")


def find_or_create_subfolder(service, parent_id: str, name: str) -> str:
    query = (
        f"mimeType='application/vnd.google-apps.folder' and "
        f"name='{name}' and '{parent_id}' in parents and trashed=false"
    )
    result = (
        service.files()
        .list(q=query, fields="files(id, name)", supportsAllDrives=True, includeItemsFromAllDrives=True)
        .execute()
    )
    files = result.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    created = service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return created["id"]


def upload_file(service, local_path: Path, folder_id: str) -> dict:
    from googleapiclient.http import MediaIoBaseUpload
    from googleapiclient.errors import HttpError

    mime, _ = mimetypes.guess_type(local_path.name)
    mime = mime or "text/markdown"

    media = MediaIoBaseUpload(
        io.BytesIO(local_path.read_bytes()),
        mimetype=mime,
        resumable=True,
    )
    meta = {"name": local_path.name, "parents": [folder_id]}
    try:
        return (
            service.files()
            .create(
                body=meta,
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
    except HttpError as exc:
        if exc.resp.status == 403 and "storageQuotaExceeded" in str(exc):
            info = get_folder_info(service, folder_id)
            drive_id = info.get("driveId")
            raise SystemExit(
                "\nERRO: Service Account nao tem quota no Drive pessoal (Gmail).\n\n"
                "Opcoes:\n"
                "  A) Usar um **Disco compartilhado** (Google Workspace):\n"
                "     - Criar Shared Drive, adicionar uploader-bot@... como Gerente de conteudo\n"
                "     - Usar --folder-id dessa pasta\n"
                "  B) **Domain-wide delegation** (Workspace admin):\n"
                "     - Habilitar delegacao na service account\n"
                "     - Rodar com --impersonate email@empresa.com\n"
                "  C) Trocar para **OAuth** (conta pessoal Gmail)\n\n"
                f"Pasta atual: {info.get('name')} | driveId={drive_id or 'My Drive (Gmail)'}"
            ) from exc
        raise


def upload_sample(service, folder_id: str) -> None:
    content = f"""---
titulo: Teste AlphaFeed Drive
data: {date.today().isoformat()}
fonte: script de teste
---

# Teste de upload

Upload automatico via service account em {datetime.now().isoformat(timespec='seconds')}.
"""
    tmp = ROOT / "temp_uploads" / "_test_drive_upload.md"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(content, encoding="utf-8")

    result = upload_file(service, tmp, folder_id)
    print(f"Upload sample OK: {result['name']}")
    print(f"  ID: {result['id']}")
    print(f"  Link: {result.get('webViewLink', 'N/A')}")


def upload_export_day(service, folder_id: str, target_date: date) -> int:
    day_dir = EXPORT_ROOT / target_date.strftime("%Y-%m-%d")
    if not day_dir.exists():
        print(f"Pasta local nao encontrada: {day_dir}")
        return 0

    md_files = sorted(day_dir.glob("*.md"))
    if not md_files:
        print(f"Nenhum .md em {day_dir}")
        return 0

    subfolder_id = find_or_create_subfolder(service, folder_id, target_date.strftime("%Y-%m-%d"))
    print(f"Subpasta Drive: {target_date.isoformat()} (id={subfolder_id})")

    uploaded = 0
    for md in md_files:
        result = upload_file(service, md, subfolder_id)
        uploaded += 1
        print(f"  OK: {result['name']}")

    print(f"\n{uploaded} arquivos enviados para {target_date.isoformat()}")
    return uploaded


def resolve_folder_id(args: argparse.Namespace) -> Optional[str]:
    folder_id = args.folder_id or os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    return folder_id.strip() if folder_id else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Testa upload no Google Drive")
    parser.add_argument("--check", action="store_true", help="So testa autenticacao")
    parser.add_argument("--list-folders", action="store_true", help="Lista pastas acessiveis")
    parser.add_argument("--list-shared-drives", action="store_true", help="Lista Discos compartilhados (Workspace)")
    parser.add_argument("--folder-id", type=str, help="ID da pasta destino no Drive")
    parser.add_argument("--impersonate", type=str, help="Email para domain-wide delegation (Workspace)")
    parser.add_argument("--upload-sample", action="store_true", help="Envia um .md de teste")
    parser.add_argument("--upload-export", action="store_true", help="Envia exportacoes de um dia")
    parser.add_argument("--date", type=str, help="Data YYYY-MM-DD (default: hoje)")
    args = parser.parse_args()

    creds_path = get_credentials_path()
    print(f"Credenciais: {creds_path}")

    service = build_drive_service(impersonate_email=args.impersonate)

    if args.check or not any([args.upload_sample, args.upload_export, args.list_folders, args.list_shared_drives]):
        check_connection(service)

    if args.list_shared_drives:
        list_shared_drives(service)

    if args.list_folders or (args.check and not args.upload_sample and not args.upload_export):
        list_shared_folders(service)

    folder_id = resolve_folder_id(args)
    if args.upload_sample or args.upload_export:
        if not folder_id:
            raise SystemExit(
                "Informe --folder-id ou GOOGLE_DRIVE_FOLDER_ID.\n"
                "A pasta precisa estar compartilhada com:\n"
                "  uploader-bot@upload-drive-499020.iam.gserviceaccount.com"
            )

    if args.upload_sample:
        upload_sample(service, folder_id)

    if args.upload_export:
        target = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else date.today()
        upload_export_day(service, folder_id, target)


if __name__ == "__main__":
    main()
