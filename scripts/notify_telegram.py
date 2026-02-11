#!/usr/bin/env python3
"""
Script para enviar notificacoes incrementais de clusters via Telegram.

Busca clusters que:
  - ja tem resumo gerado (resumo_cluster IS NOT NULL)
  - nao foram notificados (ja_notificado = False)
  - nao sao irrelevantes

Envia no formato:
  [EMOJI] [PRIORIDADE] TITULO
  TAG | FONTES
  ---
  Resumo (primeiras 500 chars)
  ---
  [Link para frontend]

Uso:
    # Configurar variaveis de ambiente ANTES:
    #   TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
    #   TELEGRAM_CHAT_ID  = "-1001234567890"  (pode ser grupo ou canal)
    #
    # Pode colocar no backend/.env ou exportar diretamente.

    conda activate pymc2
    python scripts/notify_telegram.py                # envia pendentes
    python scripts/notify_telegram.py --dry-run      # simula sem enviar
    python scripts/notify_telegram.py --limit 5      # limita a 5 clusters
    python scripts/notify_telegram.py --mark-all     # marca todos como notificados (sem enviar)
"""

import sys
import os
import argparse
import time
from pathlib import Path

# Setup paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_DIR))

# Load .env
from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / "backend" / ".env")


PRIORIDADE_EMOJI = {
    "P1_CRITICO": "🔴",
    "P2_ESTRATEGICO": "🟡",
    "P3_MONITORAMENTO": "🟢",
}

FRONTEND_BASE_URL = os.getenv("FRONTEND_URL", "http://localhost:8000/frontend")


def formatar_mensagem_telegram(cluster) -> str:
    """Formata um ClusterEvento em mensagem Markdown para Telegram."""
    emoji = PRIORIDADE_EMOJI.get(cluster.prioridade, "⚪")
    prio_label = (cluster.prioridade or "").replace("_", " ")
    titulo = cluster.titulo_cluster or "Sem titulo"
    tag = cluster.tag or "Sem tag"
    resumo = cluster.resumo_cluster or "Resumo indisponivel"

    # Trunca resumo
    if len(resumo) > 600:
        resumo = resumo[:597] + "..."

    # Conta artigos
    total = cluster.total_artigos or 0
    tipo_label = (cluster.tipo_fonte or "nacional").upper()

    msg = (
        f"{emoji} *{prio_label}*\n"
        f"*{_escape_md(titulo)}*\n\n"
        f"📌 {_escape_md(tag)} | {tipo_label} | {total} fontes\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"{_escape_md(resumo)}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🔗 [Ver no AlphaFeed]({FRONTEND_BASE_URL})"
    )
    return msg


def _escape_md(text: str) -> str:
    """Escapa caracteres especiais do MarkdownV2 do Telegram."""
    # Para MarkdownV2, precisamos escapar: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # Mas usamos Markdown simples (parse_mode=Markdown), entao so escapamos _ e *
    # dentro do texto (nao nos delimitadores de negrito)
    return text.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")


def enviar_telegram(token: str, chat_id: str, mensagem: str) -> bool:
    """Envia mensagem via Telegram Bot API."""
    import urllib.request
    import urllib.parse
    import json

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensagem,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("ok", False)
    except Exception as e:
        print(f"  [ERRO] Telegram API: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Envia notificacoes Telegram de clusters pendentes")
    parser.add_argument("--dry-run", action="store_true", help="Simula sem enviar")
    parser.add_argument("--limit", type=int, default=50, help="Max clusters a notificar (default: 50)")
    parser.add_argument("--mark-all", action="store_true", help="Marca todos como notificados sem enviar")
    args = parser.parse_args()

    # Valida config
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not args.dry_run and not args.mark_all:
        if not token or not chat_id:
            print("[ERRO] Variaveis TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nao configuradas.")
            print("       Adicione ao backend/.env ou exporte no ambiente.")
            print("       Use --dry-run para simular sem enviar.")
            sys.exit(1)

    # Conecta ao banco
    from backend.database import SessionLocal
    from backend.crud import get_clusters_nao_notificados, marcar_cluster_notificado, marcar_clusters_notificados_em_lote

    db = SessionLocal()
    try:
        clusters = get_clusters_nao_notificados(db, limit=args.limit)
        print(f"📬 {len(clusters)} clusters pendentes de notificacao")

        if not clusters:
            print("✅ Nada a notificar.")
            return

        # --mark-all: marca sem enviar
        if args.mark_all:
            ids = [c.id for c in clusters]
            total = marcar_clusters_notificados_em_lote(db, ids)
            print(f"✅ {total} clusters marcados como notificados (sem envio)")
            return

        enviados = 0
        erros = 0

        for cluster in clusters:
            msg = formatar_mensagem_telegram(cluster)

            if args.dry_run:
                print(f"\n{'='*50}")
                print(msg)
                print(f"{'='*50}")
                enviados += 1
                continue

            ok = enviar_telegram(token, chat_id, msg)
            if ok:
                marcar_cluster_notificado(db, cluster.id)
                enviados += 1
                print(f"  ✅ Cluster {cluster.id}: '{cluster.titulo_cluster[:50]}...' enviado")
            else:
                erros += 1
                print(f"  ❌ Cluster {cluster.id}: falha no envio")

            # Rate limit do Telegram: max 30 msg/s em grupos, 1 msg/s em channels
            time.sleep(1.0)

        print(f"\n📊 Resultado: {enviados} enviados, {erros} erros")
        if args.dry_run:
            print("   (dry-run: nenhum envio real, nenhum marcado)")

    finally:
        db.close()


if __name__ == "__main__":
    main()
