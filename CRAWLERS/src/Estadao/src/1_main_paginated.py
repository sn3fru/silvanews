import json
import requests
from bs4 import BeautifulSoup
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Dict
from pathlib import Path

OUTPUT_PATH = "../output/noticias_estadao.json"

# ========================================================
# LISTAGEM DE NOTÍCIAS VIA API
# ========================================================

def get_noticias_list_api(offset=0, size=20):
    url = "https://www.estadao.com.br/pf/api/v3/content/fetch/story-feed-query"

    payload = {
        "body": json.dumps({
            "query": {
                "filtered": {
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"type": "story"}},
                                {"term": {"revision.published": 1}}
                            ],
                            "must_not": [
                                {"term": {"subtype": "tudo_sobre_story"}},
                                {
                                    "nested": {
                                        "path": "taxonomy.sections",
                                        "query": {
                                            "bool": {
                                                "should": [
                                                    {"term": {"taxonomy.sections._id": "/fora-de-ultimas"}},
                                                    {"term": {"taxonomy.sections._id": "/paladar/radar"}}
                                                ]
                                            }
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }),
        "headlineSearch": "",
        "included_fields": ",".join([
            "_id", "type", "subtype", "created_date", "display_date", "first_publish_date",
            "last_updated_date", "publish_date", "label.basic", "headlines.basic", "subheadlines.basic",
            "description.basic", "taxonomy.primary_section", "taxonomy.sections", "taxonomy.tags",
            "owner", "content_elements", "promo_items.basic", "credits", "canonical_url"
        ]),
        "offset": offset,
        "params": json.dumps({"cleanContentElements": True}),
        "query": "",
        "sectionsToFilter": [],
        "size": size,
        "sort": ""
    }

    params = {
        "query": json.dumps(payload),
        "d": "2023",
        "mxId": "00000000",
        "_website": "estadao"
    }

    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, params=params)
    print(f"Status {response.status_code} para offset={offset}")

    noticias = []
    if response.status_code == 200:
        data = response.json()
        for item in data.get("content_elements", []):
            try:
                noticias.append({
                    "categoria": item.get("taxonomy", {}).get("primary_section", {}).get("name", ""),
                    "titulo": item.get("headlines", {}).get("basic", "").strip(),
                    "subtitulo": item.get("description", {}).get("basic", "").strip(),
                    "link": "https://www.estadao.com.br" + item.get("canonical_url", ""),
                    "data_publicacao": item.get("publish_date", ""),
                    # "autor": item.get("credits", {}).get("by", [{}])[0].get("name", ""),
                    "fonte": "Estadão"
                })
            except Exception as e:
                print("Erro ao processar item:", e)
    else:
        print("Erro ao acessar a API:", response.text)

    return noticias


# ========================================================
# DETALHE COMPLETO DA NOTÍCIA
# ========================================================

def extrair_detalhe_noticia(session, url):
    try:
        response = session.get(url)
        html = response.content.decode('utf-8')
        soup = BeautifulSoup(html, 'html.parser')

        # Extrai o corpo da matéria
        texto = []
        for p in soup.select('p[data-component-name="paragraph"]'):
            texto.append(p.get_text(strip=True))
        texto_completo = "\n".join(texto)

        # Extrai as datas (caso queira validar por segurança)
        data_publicacao = ""
        data_ultima_modificacao = ""

        bloco_datas = soup.select_one(".principal-dates")
        if bloco_datas:
            time_tags = bloco_datas.find_all("time")
            if len(time_tags) >= 1:
                raw_pub = time_tags[0].get_text(strip=True)
                try:
                    dt = datetime.strptime(raw_pub, "%d/%m/%Y | %Hh%M")
                    data_publicacao = dt.isoformat()
                except Exception as e:
                    print(f"[data_publicacao] Erro ao converter '{raw_pub}':", e)

            if len(time_tags) >= 2:
                raw_mod = time_tags[1].get_text(strip=True)
                try:
                    dt_mod = datetime.strptime(raw_mod, "%d/%m/%Y | %Hh%M")
                    data_ultima_modificacao = dt_mod.isoformat()
                except Exception as e:
                    print(f"[data_modificacao] Erro ao converter '{raw_mod}':", e)

        return texto_completo, data_publicacao, data_ultima_modificacao

    except Exception as e:
        print(f"[detalhe] Erro ao acessar {url}:", e)
        return "", "", ""


# ========================================================
# ID HASH
# ========================================================

def gerar_id_hash(titulo, data_publicacao):
    valor = (titulo or "") + "|" + (data_publicacao or "")
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


# ========================================================
# COLETA COMPLETA
# ========================================================

def coletar_noticias_completas():
    session = requests.Session()
    hash_dict = {}
    offset = 0
    max_paginas = 7  # Você pode ajustar esse valor para coletar mais páginas

    while True:
        lista = get_noticias_list_api(offset=offset, size=20)
        if not lista:
            break

        for n in lista:
            if not n.get("link"):
                print("Notícia sem link, pulando:", n)
                continue

            print(f"Extraindo: {n['categoria']} | {n['link']}")
            texto, data_pub, data_mod = extrair_detalhe_noticia(session, n['link'])

            # Se o texto não for encontrado, pode ser conteúdo pago, continuar mesmo assim
            n["texto_completo"] = texto or ""
            n["data_publicacao"] = data_pub or n["data_publicacao"]
            n["data_ultima_modificacao"] = data_mod
            n["id_hash"] = gerar_id_hash(n["titulo"], n["data_publicacao"])

            h = n["id_hash"]
            if h not in hash_dict:
                hash_dict[h] = n
            else:
                old = hash_dict[h]
                def dtparse(val):
                    try:
                        return datetime.fromisoformat(val.replace("Z", "+00:00"))
                    except Exception:
                        return datetime.min
                if dtparse(n["data_publicacao"]) > dtparse(old["data_publicacao"]):
                    hash_dict[h] = n

        if len(lista) < 20 or offset >= 20 * max_paginas:
            break
        offset += 20

    noticias_final = sorted(hash_dict.values(), key=lambda n: n["data_publicacao"] or "", reverse=True)
    return noticias_final


def filtrar_noticias_ultimas_24h(noticias: List[Dict]) -> List[Dict]:
    """
    Filtra as notícias publicadas nas últimas 24 horas (em UTC).

    Args:
        noticias: Lista de dicionários de notícias.

    Returns:
        Lista de notícias publicadas nas últimas 24h.
    """
    agora = datetime.now(timezone.utc)
    limite_inferior = agora - timedelta(days=1)
    noticias_filtradas = []

    for noticia in noticias:
        data_raw = noticia.get("data_publicacao")

        if not data_raw:
            continue

        try:
            # Trata strings ISO com ou sem timezone explícito
            data_publicacao = datetime.fromisoformat(data_raw.replace("Z", "+00:00"))

            # Se ainda for naive, converte para UTC assumido
            if data_publicacao.tzinfo is None:
                data_publicacao = data_publicacao.replace(tzinfo=timezone.utc)

            if limite_inferior <= data_publicacao <= agora or data_publicacao.date() == agora.date():
                noticias_filtradas.append(noticia)
        except Exception as e:
            print(f"[filtrar] Erro ao interpretar data: {data_raw} | {e}")
            continue

    return noticias_filtradas


from typing import List, Dict

def filtrar_noticias_ultimas_24h_por_categoria(noticias: List[Dict]) -> List[Dict]:
    """
    Remove notícias cujas categorias não são de interesse.

    Args:
        noticias: Lista de dicionários contendo notícias.

    Returns:
        Lista filtrada contendo apenas as notícias com categorias relevantes.
    """
    categorias_excluidas = (
        "Diversão Eldorado", "Canta Brasil", "Saúde", "Gente", "Séries",
        "Literatura", "Música", "Teatro e Dança", "Cultura", "Jornal do Carro",
        "Cinema", "Artes", "Futebol", "Televisão", "Sustentabilidade", "Esportes",
        "Comida", "TV", "Basquete", "Restaurantes e Bares", "Viagem", "Som a Pino",
        "Sneakerverso"
    )

    categorias_interesse = (
        "Negócios", "Economia", "Política", "Internacional"
    )

    return [
        noticia for noticia in noticias
        if noticia.get("categoria") and noticia["categoria"] not in categorias_excluidas
    ]


# ========================================================
# MAIN
# ========================================================

if __name__ == "__main__":
    # Caminho base do script atual
    BASE_DIR = Path(__file__).parent

    # Diretório local para salvar todas as notícias (../output)
    OUTPUT_DIR_TODAS = BASE_DIR.parent / "output"
    OUTPUT_DIR_TODAS.mkdir(parents=True, exist_ok=True)

    # Diretório separado para salvar apenas últimas 24h (../../../output)
    OUTPUT_DIR_24H = BASE_DIR.parent.parent.parent / "output"
    OUTPUT_DIR_24H.mkdir(parents=True, exist_ok=True)

    noticias = coletar_noticias_completas()

    # Salvar todas as notícias localizadas
    path_todas = OUTPUT_DIR_TODAS / "noticias_estadao_paginated.json"
    with path_todas.open("w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)
    print(f"\nTotal de notícias salvas: {len(noticias)}")

    print(f"\nArquivo '{OUTPUT_PATH}' salvo com {len(noticias)} notícias (ordenadas, ids únicos).\n")

    # Recorte últimas 24h
    noticias_24h = filtrar_noticias_ultimas_24h(noticias)
    # Recorte por Categoria
    noticias_24h_filtradas = filtrar_noticias_ultimas_24h_por_categoria(noticias_24h)
    print(f"\nTotal de notícias nas últimas 24h e em categorias de interesse: {len(noticias_24h_filtradas)}.")

    # Salvar últimas 24h em diretório separado
    path_24h = OUTPUT_DIR_24H / "noticias_estadao_ultimas_24h.json"
    with path_24h.open("w", encoding="utf-8") as f:
        json.dump(noticias_24h_filtradas, f, ensure_ascii=False, indent=2)

    print(f"\nArquivo '{path_24h.name}' salvo com {len(noticias_24h)} notícias (publicadas nas últimas 24h).\n")

    ###############################################################################

    from collections import Counter

    # Extrai as categorias presentes nas notícias, ignorando ausentes
    categorias = [noticia.get("categoria") for noticia in noticias_24h_filtradas if noticia.get("categoria")]

    # Conta as ocorrências
    contagem = Counter(categorias)

    # Exibe o resultado de forma ordenada
    for categoria, quantidade in contagem.most_common():
        print(f"{categoria}: {quantidade}")
