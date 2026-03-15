from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import requests
import hashlib

# Desabilitar avisos de SSL para evitar poluição no console
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
import json
from typing import List, Dict, Tuple
from pprint import pprint
from pathlib import Path

#########################################################

# Diretório onde o script atual está salvo
BASE_DIR = Path(__file__).parent

# Caminho absoluto baseado na localização do script
OUTPUT_PATH = BASE_DIR / ".." / ".." / "output" / "noticias_conjur_ultimas_24h.json"

# Opcional: garantir que o diretório exista
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

#########################################################

def gerar_id_hash(titulo, data_publicacao):
    valor = (titulo or "") + "|" + (data_publicacao or "")
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def extrair_detalhes_noticia(url: str) -> Tuple[str, List[str]]:
    """Extrai o texto completo e as tags da página da notícia."""
    headers = {
        "accept": "text/html",
        "accept-encoding": "",
        "user-agent": "Mozilla/5.0"
    }

    resposta = requests.get(url, headers=headers, allow_redirects=True, verify=False)
    if resposta.status_code != 200:
        print(f"Falha ao acessar {url}")
        return "", []

    soup = BeautifulSoup(resposta.content, 'html.parser')
    conteudo_div = soup.find('div', class_='the_content')
    texto_completo = conteudo_div.get_text(strip=True) if conteudo_div else ""

    tags_div = soup.find('div', class_='tags')
    tags = [a.get_text(strip=True) for a in tags_div.find_all('a')] if tags_div else []

    return texto_completo, tags

def converter_data(data_texto: str) -> str:
    """Converte uma data do Conjur para o formato ISO."""
    try:
        meses = {
            'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
            'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
            'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
        }
        partes_data, hora = data_texto.split(' às ')
        dia, mes_ext, ano = partes_data.split(' de ')
        mes = meses[mes_ext.lower()]
        return f"{ano}-{mes}-{dia.zfill(2)}T{hora}:00"
    except Exception:
        return None

def extrair_noticias(url_base: str, pagina_inicial: int = 1, pagina_final: int = 2) -> List[Dict]:
    noticias_extraidas = []
    headers = {
        "accept": "text/html",
        "accept-encoding": "",
        "user-agent": "Mozilla/5.0"
    }

    for pagina in range(pagina_inicial, pagina_final + 1):
        url = f"{url_base}/page/{pagina}/"
        resposta = requests.get(url, headers=headers, allow_redirects=True, verify=False)

        if resposta.status_code != 200:
            print(f"Falha ao acessar {url}")
            continue

        soup = BeautifulSoup(resposta.content, 'html.parser')
        artigos = soup.find_all('article', class_='lines')

        for artigo in artigos:
            noticia = {}
            titulo = artigo.find('h2').get_text(strip=True) if artigo.find('h2') else None
            link = artigo.find('a')['href'] if artigo.find('a') else None

            categoria_div = artigo.find('div', class_=lambda c: c and 'categorias_linha' in c)
            classes = [a.get_text(strip=True) for a in categoria_div.find_all('a')] if categoria_div else []

            if classes:
                classes = ";".join([c for c in classes])
            else:
                classes = ""

            data_publicacao = artigo.find('time').get_text(strip=True) if artigo.find('time') else None
            data_publicacao_aux = converter_data(data_publicacao) if data_publicacao else None
            texto_completo, tags = extrair_detalhes_noticia(link) if link else ("", [])

            noticia.update({
                "id_hash": gerar_id_hash(titulo, data_publicacao_aux),
                "titulo": titulo,
                "subtitulo": "",
                "categoria": classes,
                "link": link,
                "texto_completo": texto_completo,
                "data_publicacao": data_publicacao_aux,
                "data_ultima_modificacao": data_publicacao_aux,
                "tags": tags,
                "fonte": "Conjur"
            })
            noticias_extraidas.append(noticia)

    return noticias_extraidas

def filtrar_noticias_ultimas_24h(noticias: List[Dict]) -> List[Dict]:
    agora = datetime.now()
    limite_inferior = agora - timedelta(hours=24)
    noticias_24h = []

    for noticia in noticias:
        data_str = noticia.get('data_publicacao')
        if data_str:
            try:
                data_publicacao = datetime.strptime(data_str, '%Y-%m-%dT%H:%M:%S')
                if limite_inferior <= data_publicacao <= agora:
                    noticias_24h.append(noticia)
            except ValueError:
                continue
    return noticias_24h

def main():
    url_base = "https://www.conjur.com.br/noticias"
    noticias = extrair_noticias(url_base, pagina_inicial=1, pagina_final=3)
    noticias_24h = filtrar_noticias_ultimas_24h(noticias)
    pprint(noticias_24h)
    print(f"\nTotal de notícias nas últimas 24h: {len(noticias_24h)}")

    # Salva o resultado no JSON, ordenado
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias_24h, f, ensure_ascii=False, indent=2)

    print(f"\nArquivo '{OUTPUT_PATH}' salvo com {len(noticias_24h)} notícias (publicadas nas últimas 24h).\n")

if __name__ == "__main__":
    main()
