import json
import os

NOVAS_NOTICIAS_PATH = "../output/noticias_valor.json"
BANCO_PATH = "../output/dump_valor_economico.json"

def carregar_lista_json(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []

def salvar_lista_json(lista, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lista, f, ensure_ascii=False, indent=2)

def atualizar_banco():
    banco = carregar_lista_json(BANCO_PATH)
    novas_noticias = carregar_lista_json(NOVAS_NOTICIAS_PATH)

    if not banco:
        print(f"O banco estava vazio. Incluindo {len(novas_noticias)} notícias.")
        for n in novas_noticias:
            if "hash" in n and "id_hash" not in n:
                n["id_hash"] = n["hash"]
        banco_final = sorted(
            novas_noticias,
            key=lambda n: n.get("data_publicacao") or "1900-01-01T00:00:00",
            reverse=True
        )
        salvar_lista_json(banco_final, BANCO_PATH)
        print(f"Banco criado com {len(banco_final)} notícias.")
        return

    hashes_existentes = set(n.get("id_hash") for n in banco if "id_hash" in n)
    novas_para_adicionar = [
        n for n in novas_noticias
        if n.get("id_hash") and n.get("id_hash") not in hashes_existentes
    ]
    if novas_para_adicionar:
        print(f"Adicionando {len(novas_para_adicionar)} novas notícias.")
    else:
        print("Nenhuma notícia nova para adicionar.")

    todas = banco + novas_para_adicionar
    noticias_unicas = {}
    for n in todas:
        h = n.get("id_hash")
        if h and (
            h not in noticias_unicas or (n.get("data_publicacao") or "") > (noticias_unicas[h].get("data_publicacao") or "")
        ):
            noticias_unicas[h] = n

    banco_final = sorted(
        noticias_unicas.values(),
        key=lambda n: n.get("data_publicacao") or "1900-01-01T00:00:00",
        reverse=True
    )
    salvar_lista_json(banco_final, BANCO_PATH)
    print(f"Banco atualizado. Total de notícias únicas: {len(banco_final)}")

if __name__ == "__main__":
    atualizar_banco()
