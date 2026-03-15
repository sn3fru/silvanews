import requests
import json

# Desabilitar avisos de SSL para evitar poluição no console
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
import time
import hashlib
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict

# ========================================================
# CONFIGURAÇÕES
# ========================================================

API_KEY = "2zK14Zi9.hkbj9WbtOWK5Rtyfr9XgejbPTkDWfu6P"
BASE_URL = "https://cd-api.jota.info/api/indexer/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json",
    "Authorization": f"Api-Key {API_KEY}"
}

CATEGORIAS = ["tributos", "analise", "energia"]
RESULTS_PER_PAGE = 30
MAX_ARTIGOS = 150  # por categoria
OUTPUT_DIR = Path("../output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ========================================================
# FUNÇÕES DE UTILIDADE
# ========================================================

def gerar_id_hash(titulo: str, data_publicacao: str) -> str:
    base = f"{titulo.strip()}|{data_publicacao}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def filtrar_noticias_ultimas_24h(noticias: List[Dict]) -> List[Dict]:
    agora = datetime.now(timezone.utc)
    limite = agora - timedelta(days=1)
    return [
        n for n in noticias
        if datetime.fromisoformat(n["data_publicacao"].replace("Z", "+00:00")) >= limite
    ]

# ========================================================
# COLETA DE NOTÍCIAS
# ========================================================

def coletar_noticias_por_categoria(categoria: str) -> List[Dict]:
    noticias = []
    offset = 0

    while len(noticias) < MAX_ARTIGOS:
        payload = {
            "from": offset,
            "size": RESULTS_PER_PAGE,
            "query": {
                "bool": {
                    "should": [
                        {
                            "bool": {
                                "filter": [
                                    {"match": {"source.type": "cms.newsletter"}},
                                    {"match": {"vertical.slug": categoria}}
                                ]
                            }
                        },
                        {
                            "bool": {
                                "filter": [
                                    {"match": {"source.type": "wp.post"}},
                                    {"match": {"categories.slug.keyword": categoria}},
                                    {"term": {"source.recycled": False}}
                                ]
                            }
                        }
                    ],
                    "minimum_should_match": 1
                }
            },
            "sort": [
                {"source.published_at": {"order": "desc"}},
                {"_score": {"order": "desc"}}
            ],
            "highlight": {
                "pre_tags": [""],
                "post_tags": [""],
                "fields": {
                    "content.plain": {}
                }
            }
        }

        resp = requests.post(BASE_URL, headers=HEADERS, json=payload, verify=False)
        if resp.status_code != 200:
            print(f"[erro {resp.status_code}] offset={offset} categoria={categoria}")
            break

        dados = resp.json()
        hits = dados.get("hits", {}).get("hits", [])
        if not hits:
            break

        for item in hits:
            try:
                doc = item["_source"]
                src = doc["source"]
                title = doc["title"].get("headline", "")
                data_pub = src["published_at"]
                texto_completo = doc["content"].get("plain", "")
                slug = src["slug"]
                link = f"https://www.jota.info/{categoria}/{slug}" if not src.get("uri") else src["uri"]
                raw_subhead = doc["title"].get("subhead", "")
                resumo = "" if raw_subhead in [None, "null"] else raw_subhead

                noticias.append({
                    "id_hash": gerar_id_hash(title, data_pub),
                    "titulo": title,
                    "subtitulo": resumo,
                    "categoria": categoria,
                    "link": link,
                    "texto_completo": texto_completo,
                    "data_publicacao": data_pub,
                    "data_ultima_modificacao": data_pub,
                    "tags": [],
                    "fonte": "JOTA"
                })
            except Exception as e:
                print(f"[erro ao processar item] {e}")
                continue

        offset += RESULTS_PER_PAGE
        time.sleep(0.3)

    return noticias

# ========================================================
# EXECUÇÃO
# ========================================================

if __name__ == '__main__':
    # Caminho base do script atual
    BASE_DIR = Path(__file__).parent

    # Diretório local para salvar todas as notícias (../output)
    OUTPUT_DIR_TODAS = BASE_DIR.parent / "output"
    OUTPUT_DIR_TODAS.mkdir(parents=True, exist_ok=True)

    # Diretório separado para salvar apenas últimas 24h (../../../output)
    OUTPUT_DIR_24H = BASE_DIR.parent.parent.parent / "output"
    OUTPUT_DIR_24H.mkdir(parents=True, exist_ok=True)

    todas_noticias = []
    for categoria in CATEGORIAS:
        print(f"Coletando notícias da categoria '{categoria}'.")
        noticias = coletar_noticias_por_categoria(categoria)
        print(f"Total de notícias coletadas para a categoria '{categoria}': {len(noticias)}.\n")
        todas_noticias.extend(noticias)

    print(f"Total de notícias coletadas nas {len(CATEGORIAS)} categorias pesquisadas: {len(todas_noticias)}.")

    # Salvar todas
    with (OUTPUT_DIR_TODAS / "noticias_jota_paginated.json").open("w", encoding="utf-8") as f:
        json.dump(todas_noticias, f, ensure_ascii=False, indent=2)

    # Salvar últimas 24h
    ultimas_24h = filtrar_noticias_ultimas_24h(todas_noticias)
    print(f"Total de notícias publicadas nas últimas 24h: {len(ultimas_24h)}.")
    with (OUTPUT_DIR_24H / "noticias_jota_ultimas_24h.json").open("w", encoding="utf-8") as f:
        json.dump(ultimas_24h, f, ensure_ascii=False, indent=2)
