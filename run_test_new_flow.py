#!/usr/bin/env python3
"""
Testa o novo fluxo de agrupamento/priorização (fato gerador, heurística fonte, referente qualidade, multi-agent gating).

- Por padrão: processa até N artigos PENDENTES do dia (sem misturar outras datas).
- --reprocess: reseta N artigos já processados do dia para pendente e reprocessa.
- --full-day: reprocessa TODO o dia (reseta artigos + remove clusters do dia + pipeline completo). Equivalente a reprocess_today.py. Não reingere — usa os mesmos dados brutos.

Uso:
  python run_test_new_flow.py                    # até 10 pendentes de hoje
  python run_test_new_flow.py --sample 5         # até 5 pendentes
  python run_test_new_flow.py --reprocess        # reseta 10 artigos de hoje e reprocessa
  python run_test_new_flow.py --full-day        # reprocessa TUDO de hoje (sem misturar datas)
  python run_test_new_flow.py --full-day --day 2026-03-03
"""

import os
import sys
import argparse
from pathlib import Path

# Projeto na raiz
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Carrega .env antes de importar backend/process_articles
def _load_env():
    try:
        from dotenv import load_dotenv
        env_file = ROOT / "backend" / ".env"
        if env_file.exists():
            load_dotenv(env_file)
    except Exception:
        pass

_load_env()

# Imports após env
from backend.database import SessionLocal
from backend.utils import get_date_brasil_str
from sqlalchemy import func


def main():
    parser = argparse.ArgumentParser(
        description="Testa o novo fluxo (fato gerador, heurística fonte, multi-agent gating) com amostra de notícias de hoje."
    )
    parser.add_argument("--sample", "-n", type=int, default=10,
                        help="Número máximo de artigos a processar (default: 10)")
    parser.add_argument("--day", type=str, default=None,
                        help="Data no formato YYYY-MM-DD (default: hoje em GMT-3)")
    parser.add_argument("--reprocess", action="store_true",
                        help="Resetar N artigos já processados do dia para pendente e reprocessar")
    parser.add_argument("--full-day", action="store_true",
                        help="Reprocessar TODO o dia (reseta artigos + remove clusters do dia + pipeline). Não reingere.")
    args = parser.parse_args()

    day_str = args.day or get_date_brasil_str()
    sample = max(1, min(args.sample, 100))

    if not os.getenv("GEMINI_API_KEY"):
        print("ERRO: GEMINI_API_KEY não configurada. Configure em backend/.env")
        sys.exit(1)
    if not os.getenv("DATABASE_URL"):
        print("ERRO: DATABASE_URL não configurada. Configure em backend/.env")
        sys.exit(1)

    # --full-day: delega ao reprocess_today (reprocessar tudo do dia, sem misturar datas)
    if args.full_day:
        from reprocess_today import verificar_conexao_banco, reprocessar_data
        print("=" * 60)
        print("BTG AlphaFeed — Reprocessamento completo do dia (fluxo novo)")
        print("=" * 60)
        if not verificar_conexao_banco():
            sys.exit(1)
        reprocessar_data(day_str)
        return

    print("=" * 60)
    print("BTG AlphaFeed — Teste do novo fluxo (agrupamento/priorização)")
    print("=" * 60)
    print(f"Data: {day_str} | Amostra: até {sample} artigos | Reprocessar: {args.reprocess}")
    print()

    db = SessionLocal()
    try:
        from backend.database import ArtigoBruto

        if args.reprocess:
            # Busca artigos de hoje que já foram processados (ou pronto_agrupar) para resetar
            candidatos = db.query(ArtigoBruto).filter(
                func.date(ArtigoBruto.created_at) == day_str,
                ArtigoBruto.status.in_(("processado", "pronto_agrupar"))
            ).order_by(ArtigoBruto.created_at.asc()).limit(sample).all()

            if not candidatos:
                print(f"Nenhum artigo processado/pronto_agrupar encontrado para {day_str}.")
                print("Use sem --reprocess para processar artigos já pendentes, ou carregue notícias primeiro.")
                return

            ids = [a.id for a in candidatos]
            print(f"Resetando {len(ids)} artigos para pendente (ids: {ids[:5]}{'...' if len(ids) > 5 else ''})")
            for a in candidatos:
                a.status = "pendente"
                a.cluster_id = None
            db.commit()
            print("OK. Artigos resetados. Iniciando processamento com o novo fluxo...")
        else:
            # Verifica quantos pendentes existem hoje
            n_pendentes = db.query(ArtigoBruto).filter(
                ArtigoBruto.status == "pendente",
                func.date(ArtigoBruto.created_at) == day_str
            ).count()
            if n_pendentes == 0:
                print(f"Nenhum artigo pendente para {day_str}.")
                print("Use --reprocess para reprocessar artigos já processados hoje.")
                return
            print(f"Encontrados {n_pendentes} artigos pendentes em {day_str}. Processando até {sample}...")
    finally:
        db.close()

    # Executa o pipeline completo (Etapa 1 + 2 + 3 + 4) com o novo fluxo
    import process_articles
    ok = process_articles.processar_artigos_pendentes(limite=sample, day_str=day_str)

    if ok:
        print("\n[OK] Teste do novo fluxo concluído. Verifique clusters e resumos no frontend.")
    else:
        print("\n[FALHA] Processamento retornou erro.")
        sys.exit(1)


if __name__ == "__main__":
    main()
