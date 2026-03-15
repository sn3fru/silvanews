import json
import requests
from bs4 import BeautifulSoup

# Desabilitar avisos de SSL para evitar poluição no console
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
from datetime import datetime, timedelta
import hashlib
from typing import List, Dict
from pathlib import Path

# --- Utilitários ---

def filtrar_noticias_ultimas_24h(noticias: List[Dict]) -> List[Dict]:
    """
    Filtra as notícias cuja 'data_publicacao' esteja dentro das últimas 24 horas.

    Args:
        noticias (List[Dict]): Lista de dicionários com chave 'data_publicacao' no formato ISO 8601.

    Returns:
        List[Dict]: Lista de notícias publicadas nas últimas 24 horas.
    """
    agora = datetime.now().astimezone()  # Data/hora atual com fuso horário local
    limite_inferior = agora - timedelta(hours=24)

    noticias_filtradas = []

    for noticia in noticias:
        data_str = noticia.get("data_publicacao")
        if data_str:
            try:
                data_publicacao = datetime.fromisoformat(data_str)
                # Inclui se for dentro das últimas 24h ou mesmo dia
                if limite_inferior <= data_publicacao <= agora or data_publicacao.date() == agora.date():
                    noticias_filtradas.append(noticia)
            except ValueError:
                continue  # Ignora formatos inválidos

    return noticias_filtradas


def carregar_cookies_credenciais(caminho_json: str = "../credentials.json"):
    # Resolve o caminho absoluto relativo ao local do script atual
    caminho_absoluto = Path(__file__).parent / caminho_json

    with caminho_absoluto.open("r", encoding="utf-8") as f:
        creds = json.load(f)

    cookies_lista = creds["valor_economico"]["cookies"]

    # Monta e retorna dicionário para uso no requests
    return {cookie["name"]: cookie["value"] for cookie in cookies_lista}

def hash_noticia(titulo, data_publicacao):
    # Cria um hash único para cada notícia
    base = f"{titulo}|{data_publicacao}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()

def get_news_detail(url, cookies):
    session = requests.Session()
    for k, v in cookies.items():
        session.cookies.set(k, v, domain=".globo.com")
        session.cookies.set(k, v, domain="valor.globo.com")
    r = session.get(url, verify=False)
    soup = BeautifulSoup(r.content, "html.parser")
    # Conteúdo
    paragrafos = []
    for p in soup.find_all("p", class_="content-text__container"):
        txt = p.get_text(" ", strip=True)
        if txt:
            paragrafos.append(txt)
    conteudo_completo = "\n\n".join(paragrafos)
    # Datas
    data_publicacao = None
    data_ultima_modificacao = None
    data_pub_tag = soup.select_one("p.content-publication-data__updated time[itemprop='datePublished']")
    if data_pub_tag and data_pub_tag.has_attr('datetime'):
        data_publicacao = data_pub_tag['datetime']
    data_mod_tag = soup.select_one("span.content-publication-data__updated-relative time[itemprop='dateModified']")
    if data_mod_tag and data_mod_tag.has_attr('datetime'):
        data_ultima_modificacao = data_mod_tag['datetime']
    return conteudo_completo, data_publicacao, data_ultima_modificacao

# --- Busca de notícias paginadas ---

def fetch_paginated_news_json(cookies, max_pages=5):
    noticias_por_hash = dict()
    for pagina in range(1, max_pages+1):
        url = f"https://falkor-cda.bastian.globo.com/tenants/valor/instances/e0780b59-5b42-40b0-b7d8-35ccae6fe83c/posts/page/{pagina}"
        print(f"[{pagina}] Buscando: {url}")
        response = requests.get(url, cookies=cookies, verify=False)
        if response.status_code != 200:
            print("Erro:", response.status_code)
            break
        data = response.json()
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            try:
                bloco = item.get('content', {})
                titulo = bloco.get("title", "").strip()
                subtitulo = bloco.get("recommendationSummary", "")
                categoria = bloco.get("chapeu", {}).get("label", "")
                url_noticia = bloco.get("url", "")
                # Busca conteúdo completo e datas (detalhe)
                texto_completo, data_publicacao, data_ultima_modificacao = get_news_detail(url_noticia, cookies)
                # Gera hash único
                noticia_hash = hash_noticia(titulo, data_publicacao)
                if noticia_hash in noticias_por_hash:
                    continue
                noticia = {
                    "id_hash": noticia_hash,
                    "titulo": titulo,
                    "subtitulo": subtitulo,
                    "categoria": categoria,
                    "link": url_noticia,
                    "texto_completo": texto_completo,
                    "data_publicacao": data_publicacao,
                    "data_ultima_modificacao": data_ultima_modificacao,
                    "tags": [],
                    "fonte": "Valor Econômico"
                }
                noticias_por_hash[noticia_hash] = noticia
                print(f" - {titulo} [{data_publicacao}]")
            except Exception as e:
                print("Erro processando notícia:", e)
    # Ordena do mais recente para o mais antigo
    def sort_key(x):
        try:
            return noticias_por_hash[x].get("data_publicacao") or ""
        except:
            return ""
    ordered = [noticias_por_hash[k] for k in sorted(noticias_por_hash, key=sort_key, reverse=True)]
    return ordered

# --- Principal ---

if __name__ == "__main__":
    # Caminho base do script atual
    BASE_DIR = Path(__file__).parent

    # Diretório local para salvar todas as notícias (../output)
    OUTPUT_DIR_TODAS = BASE_DIR.parent / "output"
    OUTPUT_DIR_TODAS.mkdir(parents=True, exist_ok=True)

    # Diretório separado para salvar apenas últimas 24h (../../../output)
    OUTPUT_DIR_24H = BASE_DIR.parent.parent.parent / "output"
    OUTPUT_DIR_24H.mkdir(parents=True, exist_ok=True)

    # Carregar cookies e buscar notícias
    cookies = carregar_cookies_credenciais()
    noticias = fetch_paginated_news_json(cookies, max_pages=1)

    # Salvar todas as notícias localizadas
    path_todas = OUTPUT_DIR_TODAS / "noticias_valor_paginated.json"
    with path_todas.open("w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)
    print(f"\nTotal de notícias salvas: {len(noticias)}")

    # Recorte últimas 24h
    noticias_24h = filtrar_noticias_ultimas_24h(noticias)
    print(f"\nTotal de notícias nas últimas 24h: {len(noticias_24h)}")

    # Salvar últimas 24h em diretório separado
    path_24h = OUTPUT_DIR_24H / "noticias_valor_ultimas_24h.json"
    with path_24h.open("w", encoding="utf-8") as f:
        json.dump(noticias_24h, f, ensure_ascii=False, indent=2)

    print(f"\nArquivo '{path_24h.name}' salvo com {len(noticias_24h)} notícias (publicadas nas últimas 24h).\n")