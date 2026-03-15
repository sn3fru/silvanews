from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup

# Desabilitar avisos de SSL para evitar poluição no console
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
import hashlib
import json
from pathlib import Path

#########################################################

# Diretório onde o script atual está salvo
BASE_DIR = Path(__file__).parent

# Caminho absoluto baseado na localização do script
OUTPUT_PATH = BASE_DIR / ".." / ".." / "output" / "noticias_brazil_journal_ultimas_24h.json"

# Opcional: garantir que o diretório exista
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

#########################################################


def gerar_id_hash(titulo, data_publicacao):
    valor = (titulo or "") + "|" + (data_publicacao or "")
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


def converter_data_brazil_journal(data_str: str) -> str:
    """
    Converte datas como '20 de julho de 2025' para 'YYYY-MM-DDTHH:MM:SS'.
    Sempre assume o horário como 23:59:59.
    """
    meses = {
        'janeiro': '01', 'fevereiro': '02', 'março': '03', 'abril': '04',
        'maio': '05', 'junho': '06', 'julho': '07', 'agosto': '08',
        'setembro': '09', 'outubro': '10', 'novembro': '11', 'dezembro': '12'
    }
    try:
        partes = data_str.strip().split(' de ')
        dia, mes_nome, ano = partes
        mes = meses[mes_nome.lower()]
        return f"{ano}-{mes}-{dia.zfill(2)}T23:59:59"
    except Exception:
        return None


def extract_article_full_data(article_url: str):
    response = requests.get(article_url, verify=False)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    date_element = soup.find("time", class_="post-time")
    date = date_element.get_text(strip=True) if date_element else "Data não encontrada"

    text_element = soup.find("div", class_="post-content-text")
    full_text = text_element.get_text(strip=True) if text_element else "Texto não encontrado"

    tags_container = soup.find("nav", class_="post-tags")
    tags = [tag.get_text(strip=True) for tag in tags_container.find_all("div", class_="post-tags-item")] if tags_container else []

    return date, full_text, tags


def scrape_brazil_journal():
    urls = [
        "http://braziljournal.com/negocios/",
        "http://braziljournal.com/economia/",
        "http://braziljournal.com/tecnologia/"
    ]

    articles_data = []

    for url in urls:
        response = requests.get(url, verify=False)
        soup = BeautifulSoup(response.text, "html.parser")

        articles = soup.find_all("figcaption", class_="boxarticle-infos")

        for article in articles:
            category_element = article.find("p", class_="boxarticle-infos-tag")
            category = category_element.get_text(strip=True) if category_element else "Categoria não encontrada"

            title_element = article.find("h2", class_="boxarticle-infos-title")
            link_element = title_element.find("a") if title_element else None

            title = link_element.get_text(strip=True) if link_element else "Título não encontrado"
            article_url = link_element["href"] if link_element and "href" in link_element.attrs else "URL não encontrada"

            date, full_text, tags = extract_article_full_data(article_url)
            date_aux = converter_data_brazil_journal(date)

            articles_data.append({
                "id_hash": gerar_id_hash(title, date_aux),
                "titulo": title,
                "subtitulo": "",
                "categoria": category,
                "link": article_url,
                "texto_completo": full_text,
                "data_publicacao": date_aux,
                "data_ultima_modificacao": date_aux,
                "tags": tags,
                "fonte": "Brazil Journal"
            })

    return articles_data


def filtrar_noticias_ultimas_24h(noticias):
    agora = datetime.now()
    limite_inferior = agora - timedelta(hours=24)
    noticias_filtradas = []

    for noticia in noticias:
        data_str = noticia.get("data_publicacao")
        if data_str:
            try:
                data_publicacao = datetime.strptime(data_str, "%Y-%m-%dT%H:%M:%S")
                if limite_inferior.date() <= data_publicacao.date() <= agora.date():
                    noticias_filtradas.append(noticia)
            except Exception:
                continue
    return noticias_filtradas


def main():
    # Execução principal
    dados = scrape_brazil_journal()

    noticias_24h = filtrar_noticias_ultimas_24h(dados)

    print(f"\nTotal de notícias nas últimas 24h: {len(noticias_24h)}")

    # Salva o resultado no JSON, ordenado
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias_24h, f, ensure_ascii=False, indent=2)

    print(f"\nArquivo '{OUTPUT_PATH}' salvo com {len(noticias_24h)} notícias (publicadas nas últimas 24h).\n")


if __name__ == '__main__':
    main()
