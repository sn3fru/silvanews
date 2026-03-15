"""
Script de teste para o Agente de Resumo Diário — Chamada Unificada v3.

Uso:
    cd <RAIZ_DO_PROJETO>
    python test_resumo_diario.py

O script:
  1. Importa o agente unificado
  2. Chama gerar_resumo_diario() — 1 chamada LLM cobrindo todos os angulos
  3. Imprime resultado por secao + mensagem WhatsApp formatada
  4. Salva resultado em test_resumo_output.json
"""

import json
import sys
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv
    for env_candidate in [os.path.join(ROOT, "backend", ".env"), os.path.join(ROOT, ".env")]:
        if os.path.exists(env_candidate):
            load_dotenv(env_candidate)
            break
except ImportError:
    pass

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("[ERRO] GEMINI_API_KEY nao encontrada. Verifique backend/.env")
    sys.exit(1)

print(f"[Test] GEMINI_API_KEY ok ({api_key[:8]}...)")

try:
    from agents.resumo_diario.agent import gerar_resumo_diario, formatar_whatsapp
    print("[Test] Imports ok")
except Exception as e:
    print(f"[ERRO] Import falhou: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\n{'='*60}")
print("  TESTE — AGENTE DE RESUMO DIARIO (v3 Unificado)")
print(f"{'='*60}\n")

t0 = time.time()
resultado = gerar_resumo_diario()
elapsed = time.time() - t0

print(f"\n{'='*60}")
print(f"  RESULTADO ({elapsed:.1f}s)")
print(f"{'='*60}\n")

if resultado.get("ok"):
    print(f"  Data: {resultado['data']}")
    print(f"  Clusters avaliados: {len(resultado['clusters_avaliados_ids'])}")
    print(f"  Total selecionados: {len(resultado['todos_clusters_escolhidos_ids'])}")

    contract = resultado.get("contract_dict", {})
    fontes_map = resultado.get("fontes_map", {})

    tldr = contract.get("tldr_executivo")
    if tldr:
        print(f"\n  TL;DR: {tldr}\n")

    clusters = contract.get("clusters_selecionados", [])
    por_secao = {}
    for cs in clusters:
        por_secao.setdefault(cs.get("secao", "geral"), []).append(cs)

    for secao, items in por_secao.items():
        print(f"\n  --- {secao.upper()} ({len(items)} itens) ---")
        for i, cs in enumerate(items, 1):
            cid = cs["cluster_id"]
            fontes = fontes_map.get(cid, fontes_map.get(str(cid), []))
            fontes_str = ", ".join(fontes[:3]) if fontes else cs.get("fonte_principal", "")
            print(f"  {i}. {cs['titulo_whatsapp']}")
            print(f"     {cs['bullet_impacto']}")
            if fontes_str:
                print(f"     Fontes: {fontes_str}")

    print(f"\n{'='*60}")
    print("  MENSAGEM WHATSAPP (copiar abaixo)")
    print(f"{'='*60}")

    mensagens = formatar_whatsapp(resultado)
    for msg in mensagens:
        print(msg)
        print()

    print(f"  ({sum(len(m) for m in mensagens)} chars, {len(mensagens)} mensagem(ns))")

    resultado_json = dict(resultado)
    if "fontes_map" in resultado_json:
        resultado_json["fontes_map"] = {str(k): v for k, v in resultado_json["fontes_map"].items()}
    output_path = os.path.join(ROOT, "test_resumo_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(resultado_json, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON salvo: {output_path}")

    whatsapp_path = os.path.join(ROOT, "test_resumo_whatsapp.txt")
    with open(whatsapp_path, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(mensagens))
    print(f"  WhatsApp salvo: {whatsapp_path}")

else:
    print(f"  FALHOU: {resultado.get('error', 'Desconhecido')}")

print(f"\n[Test] Concluido em {elapsed:.1f}s.")
