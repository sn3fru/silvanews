#!/usr/bin/env python3
"""
Módulo de Disseminação Telegram — Daily Briefing / Morning Call.

Consome clusters P1/P2 do dia, gera um briefing via LLM (Gemini Flash)
e envia para canal/grupo do Telegram.

Spec completa: docs/TELEGRAM_MODULE_SPEC.md

Uso direto (teste):
    python -m backend.broadcaster --dry-run
    python -m backend.broadcaster

Via CLI wrapper:
    python send_telegram.py --dry-run
"""

import os
import sys
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Setup paths
_PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_DIR))

from dotenv import load_dotenv
load_dotenv(_PROJECT_DIR / "backend" / ".env")


class TelegramBroadcaster:
    """
    Gera e envia Daily Briefing sintetizado para Telegram.
    
    Fluxo:
      1. Query clusters P1/P2 do dia
      2. Monta contexto JSON simplificado
      3. Gemini Flash gera texto HTML formatado
      4. Split em mensagens ≤4000 chars
      5. Envia via Telegram Bot API
      6. Registra log de auditoria
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._gemini_client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token) and bool(self.chat_id)

    # ------------------------------------------------------------------
    # 1. QUERY: Busca clusters P1/P2 do dia + contexto v2 (grafo)
    # ------------------------------------------------------------------
    def get_clusters_do_dia(self, day_str: Optional[str] = None) -> List[Dict]:
        """
        Busca clusters ativos P1/P2 do dia.
        Enriquece cada cluster com contexto temporal do grafo v2 (se disponivel).
        Retorna lista de dicts simplificados para o LLM.
        """
        from backend.database import SessionLocal, ClusterEvento
        from sqlalchemy import func

        db = SessionLocal()
        try:
            from backend.utils import get_date_brasil_str
            hoje = day_str or get_date_brasil_str()

            clusters = (
                db.query(ClusterEvento)
                .filter(
                    ClusterEvento.status == 'ativo',
                    func.date(ClusterEvento.created_at) == hoje,
                    ClusterEvento.prioridade.in_(['P1_CRITICO', 'P2_ESTRATEGICO']),
                    ClusterEvento.tag != 'IRRELEVANTE',
                )
                .order_by(
                    # P1 primeiro, depois P2; dentro de cada, por total de artigos desc
                    ClusterEvento.prioridade.asc(),
                    ClusterEvento.total_artigos.desc(),
                )
                .all()
            )

            resultado = []
            for c in clusters:
                entry = {
                    "id": c.id,
                    "titulo": c.titulo_cluster or "",
                    "prioridade": c.prioridade or "",
                    "resumo": (c.resumo_cluster or "")[:500],
                    "tag": c.tag or "",
                    "tipo_fonte": getattr(c, 'tipo_fonte', 'nacional') or 'nacional',
                }

                # ---- ENRIQUECIMENTO v2: Contexto temporal do grafo ----
                # Se o grafo tem historico, injeta para o LLM gerar
                # frases como "3o inquerito contra Banco Master esta semana"
                contexto_v2 = self._get_contexto_grafo(db, c.id)
                if contexto_v2:
                    entry["contexto_historico"] = contexto_v2

                resultado.append(entry)
            return resultado
        finally:
            db.close()

    @staticmethod
    def _get_contexto_grafo(db, cluster_id: int) -> str:
        """
        Busca contexto temporal do grafo v2 para um cluster.
        Retorna string com historico relevante ou vazio.
        Falha silenciosa (graceful degradation).
        """
        try:
            from backend.agents.graph_crud import get_context_for_cluster
            contexto = get_context_for_cluster(
                db=db,
                cluster_id=cluster_id,
                days_graph=7,
                days_vector=14,  # janela menor para briefing (concisao)
            )
            # Trunca para nao estourar o prompt — resumo do contexto
            if contexto and len(contexto.strip()) > 20:
                return contexto.strip()[:600]
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # 2. GERAÇÃO: LLM produz o briefing HTML
    # ------------------------------------------------------------------
    def _get_gemini_client(self):
        """Inicializa Gemini client (lazy)."""
        if self._gemini_client is not None:
            return self._gemini_client

        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY nao configurada")

        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._gemini_client = genai.GenerativeModel('gemini-2.0-flash')
        except ImportError:
            from google import genai as genai_new
            client = genai_new.Client(api_key=api_key)
            self._gemini_client = client
        return self._gemini_client

    def gerar_briefing(self, clusters: List[Dict], day_str: Optional[str] = None) -> str:
        """
        Gera texto do briefing via LLM.
        Retorna HTML formatado para Telegram.
        """
        if not clusters:
            return ""

        from backend.prompts import PROMPT_TELEGRAM_BRIEFING_V1
        from backend.utils import get_date_brasil_str

        hoje = day_str or get_date_brasil_str()
        hora = time.strftime("%H:%M")

        # Monta o prompt com os dados
        clusters_json = json.dumps(clusters, ensure_ascii=False, indent=2)
        prompt = PROMPT_TELEGRAM_BRIEFING_V1.format(
            DATA_HOJE=hoje,
            HORA_ATUAL=hora,
            CLUSTERS_JSON=clusters_json,
        )

        # Chama Gemini
        client = self._get_gemini_client()

        try:
            # google.generativeai (GenerativeModel)
            response = client.generate_content(
                prompt,
                generation_config={'temperature': 0.3, 'max_output_tokens': 4096}
            )
            text = response.text or ""
        except AttributeError:
            # google.genai (Client)
            response = client.models.generate_content(
                model='gemini-2.0-flash',
                contents=prompt,
                config={'temperature': 0.3, 'max_output_tokens': 4096}
            )
            text = response.text or ""

        # Limpa blocos de código se o LLM adicionou
        text = text.strip()
        if text.startswith("```html"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    # ------------------------------------------------------------------
    # 3. SPLITTER: Quebra em mensagens ≤4000 chars
    # ------------------------------------------------------------------
    @staticmethod
    def split_message(text: str, limit: int = 4000) -> List[str]:
        """
        Divide texto em partes respeitando o limite do Telegram.
        Tenta quebrar em parágrafos (\n\n), senão em linhas (\n).
        """
        if len(text) <= limit:
            return [text]

        parts = []
        remaining = text

        while remaining:
            if len(remaining) <= limit:
                parts.append(remaining)
                break

            # Tenta quebrar em parágrafo
            cut_pos = remaining.rfind('\n\n', 0, limit)
            if cut_pos < limit // 3:
                # Tenta quebrar em linha
                cut_pos = remaining.rfind('\n', 0, limit)
            if cut_pos < limit // 3:
                # Força corte no limite
                cut_pos = limit

            parts.append(remaining[:cut_pos].rstrip())
            remaining = remaining[cut_pos:].lstrip()

        # Numera se tiver múltiplas partes
        if len(parts) > 1:
            total = len(parts)
            parts = [f"📄 Parte {i+1}/{total}\n\n{p}" for i, p in enumerate(parts)]

        return parts

    # ------------------------------------------------------------------
    # 4. ENVIO: POST na API do Telegram
    # ------------------------------------------------------------------
    def enviar_mensagem(self, text: str, parse_mode: str = "HTML") -> Tuple[bool, str]:
        """
        Envia uma mensagem via Telegram Bot API.
        Retorna (sucesso, detalhes).
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("ok"):
                    return True, "OK"
                return False, body.get("description", "Unknown error")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            return False, f"HTTP {e.code}: {error_body[:200]}"
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------
    # 5. IDEMPOTÊNCIA: Verifica se já enviou hoje
    # ------------------------------------------------------------------
    def ja_enviou_hoje(self, day_str: Optional[str] = None) -> bool:
        """Verifica se já existe log de envio bem-sucedido para o dia."""
        try:
            from backend.database import SessionLocal, LogProcessamento
            from sqlalchemy import func

            from backend.utils import get_date_brasil_str
            hoje = day_str or get_date_brasil_str()

            db = SessionLocal()
            try:
                count = (
                    db.query(LogProcessamento)
                    .filter(
                        LogProcessamento.componente == 'broadcaster',
                        LogProcessamento.nivel == 'INFO',
                        func.date(LogProcessamento.created_at) == hoje,
                    )
                    .count()
                )
                return count > 0
            finally:
                db.close()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 6. AUDITORIA: Registra log
    # ------------------------------------------------------------------
    def registrar_log(self, sucesso: bool, detalhes: Dict):
        """Registra log de envio no banco."""
        try:
            from backend.database import SessionLocal
            from backend.crud import create_log

            db = SessionLocal()
            try:
                nivel = "INFO" if sucesso else "ERROR"
                mensagem = "Briefing diario enviado para Telegram" if sucesso else "Falha no envio do briefing Telegram"
                create_log(
                    db=db,
                    nivel=nivel,
                    componente="broadcaster",
                    mensagem=mensagem,
                    detalhes=detalhes,
                )
            finally:
                db.close()
        except Exception as e:
            print(f"  [broadcaster] Erro ao registrar log: {e}")

    # ------------------------------------------------------------------
    # FLUXO PRINCIPAL
    # ------------------------------------------------------------------
    def run(
        self,
        day_str: Optional[str] = None,
        dry_run: bool = False,
        force: bool = False,
    ) -> bool:
        """
        Executa o fluxo completo: query → LLM → split → envio → log.
        
        Args:
            day_str: Data no formato YYYY-MM-DD (default: hoje)
            dry_run: Se True, gera o briefing mas não envia
            force: Se True, envia mesmo se já enviou hoje
            
        Returns:
            True se sucesso (ou dry-run), False se falhou
        """
        from backend.utils import get_date_brasil_str
        hoje = day_str or get_date_brasil_str()

        print(f"\n📨 Telegram Briefing — {hoje}")

        # Validação de credenciais
        if not dry_run and not self.is_configured:
            print("  ⚠️ TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não configurados. Abortando.")
            print("  💡 Adicione ao arquivo backend/.env (LOCAL, não só no Heroku):")
            print("     TELEGRAM_BOT_TOKEN=seu_token_do_botfather")
            print("     TELEGRAM_CHAT_ID=-100XXXXXXXXXX")
            return False

        # Idempotência
        if not force and not dry_run and self.ja_enviou_hoje(hoje):
            print("  ℹ️ Briefing já enviado hoje. Use --force para reenviar.")
            return True

        # 1. Busca clusters
        print("  🔍 Buscando clusters P1/P2 do dia...")
        clusters = self.get_clusters_do_dia(hoje)
        print(f"  📊 {len(clusters)} clusters encontrados (P1/P2)")

        if not clusters:
            # ---- EDGE CASE: "DIA DE TÉDIO" ----
            # Nenhum P1/P2: feriado, domingo, etc. Aborta sem chamar LLM.
            # Nao gasta tokens, nao arrisca alucinacao.
            print("  📭 Nenhum cluster P1/P2 encontrado. Briefing cancelado (dia sem destaques).")
            self.registrar_log(True, {
                "data": hoje,
                "clusters_count": 0,
                "motivo": "Nenhum cluster P1/P2 — dia sem destaques",
            })
            return True

        # Conta contexto v2 enriquecido
        com_contexto = sum(1 for c in clusters if c.get("contexto_historico"))
        if com_contexto:
            print(f"  🧠 {com_contexto}/{len(clusters)} clusters com contexto temporal v2 (grafo)")

        # 2. Gera briefing via LLM
        print("  🤖 Gerando briefing via Gemini...")
        try:
            briefing = self.gerar_briefing(clusters, hoje)
        except Exception as e:
            print(f"  ❌ Erro ao gerar briefing: {e}")
            self.registrar_log(False, {"erro": str(e), "fase": "geracao"})
            return False

        if not briefing:
            print("  ⚠️ LLM retornou briefing vazio.")
            return False

        print(f"  📝 Briefing gerado ({len(briefing)} chars)")

        # 3. Split em mensagens
        parts = self.split_message(briefing)
        print(f"  📄 {len(parts)} mensagem(ns) para envio")

        # DRY-RUN: mostra sem enviar
        if dry_run:
            print("\n" + "=" * 60)
            print("DRY-RUN — CONTEÚDO DO BRIEFING:")
            print("=" * 60)
            for i, part in enumerate(parts):
                print(f"\n--- Parte {i+1}/{len(parts)} ({len(part)} chars) ---")
                print(part)
            print("\n" + "=" * 60)
            return True

        # 4. Envia
        print(f"  📤 Enviando para chat_id={self.chat_id}...")
        enviados = 0
        erros = []
        for i, part in enumerate(parts):
            ok, detail = self.enviar_mensagem(part)
            if ok:
                enviados += 1
                print(f"    ✅ Parte {i+1}/{len(parts)} enviada")
            else:
                erros.append(detail)
                print(f"    ❌ Parte {i+1}/{len(parts)} falhou: {detail}")
            # Rate limit: 1 msg/s
            if i < len(parts) - 1:
                time.sleep(1)

        sucesso = enviados == len(parts)

        # 5. Log de auditoria
        self.registrar_log(sucesso, {
            "data": hoje,
            "clusters_count": len(clusters),
            "message_parts": len(parts),
            "parts_sent": enviados,
            "target_chat": self.chat_id,
            "briefing_chars": len(briefing),
            "errors": erros if erros else None,
        })

        if sucesso:
            print(f"  🎉 Briefing enviado com sucesso! ({enviados} parte(s))")
        else:
            print(f"  ⚠️ Envio parcial: {enviados}/{len(parts)} partes")

        return sucesso


# ==============================================================================
# CLI: python -m backend.broadcaster
# ==============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Telegram Daily Briefing")
    parser.add_argument("--dry-run", action="store_true", help="Gera briefing sem enviar")
    parser.add_argument("--force", action="store_true", help="Reenvia mesmo se ja enviou hoje")
    parser.add_argument("--day", type=str, default=None, help="Data (YYYY-MM-DD), default=hoje")
    args = parser.parse_args()

    broadcaster = TelegramBroadcaster()
    ok = broadcaster.run(day_str=args.day, dry_run=args.dry_run, force=args.force)
    sys.exit(0 if ok else 1)
