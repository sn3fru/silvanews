#!/usr/bin/env python3
"""
Script temporário para validar resumo Barretti.
DELETAR APÓS VALIDAÇÃO (regra do projeto).

Uso:
    python tmp_test_barretti.py [--date YYYY-MM-DD]
"""

import os
import sys
import argparse
import datetime

if os.name == "nt":
    os.environ["PYTHONUTF8"] = "1"
    os.system("chcp 65001 >nul 2>&1")

# Carrega variaveis do backend/.env
_env_path = os.path.join(os.path.dirname(__file__), "backend", ".env")
if os.path.exists(_env_path):
    with open(_env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if key.strip() and not os.getenv(key.strip()):
                os.environ[key.strip()] = val


def main():
    parser = argparse.ArgumentParser(description="Teste Barretti")
    parser.add_argument("--date", type=str, default=None, help="Data no formato YYYY-MM-DD")
    args = parser.parse_args()

    from backend.database import init_database
    init_database()

    if args.date:
        target_date = datetime.date.fromisoformat(args.date)
    else:
        from agents.resumo_diario.agent import get_date_brasil
        target_date = get_date_brasil()

    print(f"\n{'#' * 70}")
    print(f"  TESTE — Resumo BARRETTI (Capital Solutions)")
    print(f"  Data: {target_date.isoformat()}")
    print(f"{'#' * 70}\n")

    from agents.resumo_diario.agent import (
        gerar_resumo_barretti,
        formatar_barretti,
    )

    res_barretti = gerar_resumo_barretti(target_date=target_date)
    if res_barretti.get("ok"):
        texto_barretti = formatar_barretti(res_barretti)
        n_barretti = len(res_barretti.get("todos_clusters_escolhidos_ids", []))
        print(f"\n  BARRETTI: {n_barretti} noticias selecionadas\n")
        print(texto_barretti)

        # --- Estatisticas ---
        print(f"\n{'#' * 70}")
        print("  ESTATISTICAS")
        print(f"{'#' * 70}")

        cb = res_barretti.get("contract_dict", {})
        n_b = len(cb.get("noticias", []))
        top5 = cb.get("top_5_temas", [])
        radars_opp = cb.get("radar_oportunidades", [])
        radars_risk = cb.get("radar_riscos", [])
        watchlist = cb.get("watchlist", [])
        actions = cb.get("action_items", [])
        perguntas = cb.get("perguntas_estrategicas", [])
        print(f"  {n_b} noticias, {len(top5)} temas, "
              f"{len(radars_opp)} oportunidades, {len(radars_risk)} riscos, "
              f"{len(watchlist)} watchlist, {len(actions)} actions, {len(perguntas)} perguntas")

        mencoes = {"btg pactual", "banco master", "daniel vorcaro", "inss", "credcesta"}
        found = set()
        for nt in cb.get("noticias", []):
            all_text = " ".join([
                nt.get("titulo", ""),
                nt.get("resumo_executivo", ""),
                nt.get("impacto_ss", ""),
            ]).lower()
            for m in mencoes:
                if m in all_text:
                    found.add(m)
        if found:
            print(f"  Menções obrigatórias encontradas: {', '.join(sorted(found))}")
        missing_m = mencoes - found
        if missing_m:
            print(f"  Menções não encontradas (ok se ausentes no dia): {', '.join(sorted(missing_m))}")
    else:
        print(f"  [ERRO BARRETTI] {res_barretti.get('error', '?')}")

    print(f"\n{'#' * 70}")
    print("  FIM DO TESTE — DELETAR ESTE SCRIPT APÓS VALIDAÇÃO")
    print(f"{'#' * 70}\n")


if __name__ == "__main__":
    main()
