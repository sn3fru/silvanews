"""
Script de teste para o Agente de Resumo Diário — MULTI-PERSONA (WhatsApp).

Uso (no Anaconda terminal):
    cd <RAIZ_DO_PROJETO>
    python test_resumo_diario.py

O script:
  1. Importa o agente multi-persona
  2. Chama gerar_resumo_diario() — 3 personas em paralelo sobre os clusters de hoje
  3. Imprime resultado por persona + mensagem WhatsApp seccionada
  4. Salva resultado em test_resumo_output.json
"""

import json
import sys
import os
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Carrega .env
try:
    from dotenv import load_dotenv
    for env_candidate in [os.path.join(ROOT, "backend", ".env"), os.path.join(ROOT, ".env")]:
        if os.path.exists(env_candidate):
            load_dotenv(env_candidate)
            print(f"[Test] .env carregado de {env_candidate}")
            break
except ImportError:
    print("[Test] python-dotenv não disponível")

# Verifica variáveis
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("❌ ERRO: GEMINI_API_KEY não encontrada.")
    sys.exit(1)
print(f"[Test] GEMINI_API_KEY encontrada ({api_key[:8]}...)")

db_url = os.getenv("DATABASE_URL")
if db_url:
    print(f"[Test] DATABASE_URL encontrada ({db_url[:30]}...)")

print(f"\n{'='*60}")
print("  TESTE MULTI-PERSONA — AGENTE DE RESUMO DIÁRIO (WhatsApp)")
print(f"{'='*60}\n")

try:
    from agents.resumo_diario.agent import gerar_resumo_diario, formatar_whatsapp
    print("[Test] Imports OK ✅\n")
except Exception as e:
    print(f"❌ ERRO de import: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Executa
print("[Test] Chamando gerar_resumo_diario() com 3 personas em paralelo...\n")
t0 = time.time()

resultado = gerar_resumo_diario()

elapsed = time.time() - t0

print(f"\n{'='*60}")
print(f"  RESULTADO (executado em {elapsed:.1f}s)")
print(f"{'='*60}\n")

if resultado.get("ok"):
    print(f"✅ Sucesso!")
    print(f"   Data: {resultado['data']}")
    print(f"   Clusters avaliados: {len(resultado['clusters_avaliados_ids'])}")
    print(f"   Total escolhidos (união): {len(resultado['todos_clusters_escolhidos_ids'])}")

    # Por persona
    personas_res = resultado.get("personas_resultados", {})
    fontes_map = resultado.get("fontes_map", {})
    for p_key, p_res in personas_res.items():
        print(f"\n   --- {p_key.upper()} ---")
        if p_res["ok"] and p_res.get("contract_dict"):
            cd = p_res["contract_dict"]
            tldr = cd.get("tldr_executivo")
            if tldr:
                print(f"   TL;DR: {tldr}")
            for i, cs in enumerate(cd["clusters_selecionados"], 1):
                cid = cs["cluster_id"]
                fontes = fontes_map.get(cid, fontes_map.get(str(cid), []))
                fontes_str = ", ".join(fontes[:3]) if fontes else cs.get("fonte_principal", "")
                print(f"   {i}. {cs['titulo_whatsapp']}")
                print(f"      → {cs['bullet_impacto']}")
                print(f"      Fontes: {fontes_str}")
        else:
            print(f"   ❌ Falha: {p_res.get('error', 'Desconhecido')}")

    # ================================================================
    # MENSAGEM WHATSAPP — PRONTA PARA COPIAR
    # ================================================================
    print(f"\n{'='*60}")
    print("  COPIE A MENSAGEM ABAIXO PARA O WHATSAPP")
    print(f"{'='*60}")
    print("╔" + "═"*58 + "╗")

    mensagens = formatar_whatsapp(resultado)
    for idx, msg in enumerate(mensagens, 1):
        if idx > 1:
            print("╠" + "═"*58 + "╣")
            print(f"  (Mensagem {idx})")
        print(msg)

    print("╚" + "═"*58 + "╝")
    print(f"  ({sum(len(m) for m in mensagens)} chars total, {len(mensagens)} mensagem(ns))")

    # Salvar JSON (converter fontes_map keys int->str para serialização)
    resultado_json = dict(resultado)
    if "fontes_map" in resultado_json:
        resultado_json["fontes_map"] = {str(k): v for k, v in resultado_json["fontes_map"].items()}
    output_path = os.path.join(ROOT, "test_resumo_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(resultado_json, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON salvo em: {output_path}")

    # Salvar mensagem WhatsApp em TXT (fácil de abrir e copiar)
    whatsapp_path = os.path.join(ROOT, "test_resumo_whatsapp.txt")
    with open(whatsapp_path, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(mensagens))
    print(f"📋 Mensagem WhatsApp salva em: {whatsapp_path}")

else:
    print(f"❌ Falha: {resultado.get('error', 'Desconhecido')}")

print(f"\n[Test] Concluído em {elapsed:.1f}s.")

