"""
Script de teste para o Agente de Resumo Diario.

Uso:
    python test_resumo_diario.py                  # modo unificado (generico, terminal)
    python test_resumo_diario.py --user 1         # modo per-user (personalizado, como o frontend)
    python test_resumo_diario.py --user 1 --save  # gera e salva no banco (como o pipeline)

O modo unificado usa PROMPT_RESUMO_UNIFICADO_V1 (sem preferencias de usuario).
O modo per-user usa gerar_resumo_para_usuario(user_id) com as preferencias do banco.
"""

import json
import sys
import os
import time
import argparse

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

parser = argparse.ArgumentParser(description="Teste do agente de resumo diario")
parser.add_argument("--user", type=int, default=None, help="User ID para modo per-user (personalizado)")
parser.add_argument("--save", action="store_true", help="Salvar resumo no banco (como o pipeline)")
args = parser.parse_args()

try:
    from agents.resumo_diario.agent import gerar_resumo_diario, gerar_resumo_para_usuario, formatar_whatsapp
    print("[Test] Imports ok")
except Exception as e:
    print(f"[ERRO] Import falhou: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

if args.user:
    print(f"\n{'='*60}")
    print(f"  TESTE PER-USER — user_id={args.user}")
    print(f"{'='*60}")

    try:
        from backend.database import SessionLocal
        from backend.crud import get_usuario_by_id, get_preferencias_usuario
        db = SessionLocal()
        user = get_usuario_by_id(db, args.user)
        if not user:
            print(f"[ERRO] Usuario id={args.user} nao encontrado.")
            db.close()
            sys.exit(1)
        print(f"  Usuario: {user.nome} ({user.email})")
        prefs = get_preferencias_usuario(db, args.user)
        if prefs:
            print(f"  Tags interesse: {prefs.tags_interesse or []}")
            print(f"  Tamanho resumo: {prefs.tamanho_resumo or 'medio'}")
        else:
            print("  [AVISO] Sem preferencias definidas — usara prompt padrao.")
        db.close()
    except Exception as e:
        print(f"  [AVISO] Nao conseguiu ler preferencias: {e}")

    print()
    t0 = time.time()
    resultado = gerar_resumo_para_usuario(user_id=args.user)
    elapsed = time.time() - t0
else:
    print(f"\n{'='*60}")
    print("  TESTE UNIFICADO — Prompt generico (sem preferencias de usuario)")
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
    print(f"  Prompt version: {resultado.get('prompt_version', '?')}")

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
    print("  MENSAGEM WHATSAPP")
    print(f"{'='*60}")

    mensagens = formatar_whatsapp(resultado)
    for msg in mensagens:
        print(msg)
        print()

    print(f"  ({sum(len(m) for m in mensagens)} chars, {len(mensagens)} msg)")

    if args.save and args.user:
        try:
            from backend.database import SessionLocal
            from backend.crud import create_resumo_usuario
            texto_full = "\n\n---\n\n".join(mensagens) if mensagens else None
            db = SessionLocal()
            create_resumo_usuario(
                db, args.user, resultado["data"], template_id=None,
                clusters_avaliados=resultado.get("clusters_avaliados_ids", []),
                clusters_escolhidos=resultado.get("todos_clusters_escolhidos_ids", []),
                texto=texto_full, texto_whatsapp=texto_full,
                prompt_version=resultado.get("prompt_version"),
                metadados=resultado.get("contract_dict", {}),
            )
            db.close()
            print(f"\n  [OK] Resumo salvo no banco para user_id={args.user}")
        except Exception as e:
            print(f"\n  [ERRO] Falha ao salvar: {e}")

    resultado_json = dict(resultado)
    if "fontes_map" in resultado_json:
        resultado_json["fontes_map"] = {str(k): v for k, v in resultado_json["fontes_map"].items()}
    output_path = os.path.join(ROOT, "test_resumo_output.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(resultado_json, f, ensure_ascii=False, indent=2)
    print(f"  JSON salvo: {output_path}")

else:
    print(f"  FALHOU: {resultado.get('error', 'Desconhecido')}")

print(f"\n[Test] Concluido em {elapsed:.1f}s.")
