import json
import requests
from bs4 import BeautifulSoup
import hashlib
from datetime import datetime

CREDENTIALS_PATH = "../credentials.json"
OUTPUT_PATH = "../output/noticias_valor.json"

def load_cookies_from_credentials():
    with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        creds = json.load(f)["valor_economico"]
    return creds["cookies"]

def set_cookies_in_session(session, cookies):
    for cookie in cookies:
        session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', None), path=cookie.get('path', '/'))

def get_noticias_list_page(session):
    url = "https://valor.globo.com/ultimas-noticias/"
    response = session.get(url)
    print("Status:", response.status_code)
    html = response.content.decode('utf-8')
    soup = BeautifulSoup(html, 'html.parser')
    noticias = []

    for item in soup.find_all("div", class_="bastian-feed-item"):
        try:
            categoria = None
            chapeu = item.select_one(".feed-post-header-chapeu a")
            if chapeu:
                categoria = chapeu.get_text(strip=True)

            titulo_tag = item.select_one(".feed-post-link")
            titulo = titulo_tag.get_text(strip=True) if titulo_tag else None
            link_tag = titulo_tag.find("a") if titulo_tag else None
            link = link_tag["href"] if link_tag and link_tag.has_attr("href") else None
            if not link:
                link = titulo_tag["href"] if titulo_tag and titulo_tag.has_attr("href") else None

            resumo_tag = item.select_one(".feed-post-body-resumo")
            subtitulo = resumo_tag.get_text(strip=True) if resumo_tag else None

            noticias.append({
                "categoria": categoria,
                "titulo": titulo,
                "subtitulo": subtitulo,
                "link": link,
                "fonte": "Valor Econômico"
            })
        except Exception as e:
            print("Erro ao processar item da listagem:", e)
    return noticias

def extrair_detalhe_noticia(session, url):
    try:
        response = session.get(url)
        html = response.content.decode('utf-8')
        soup = BeautifulSoup(html, 'html.parser')

        texto = []
        for p in soup.select('p.content-text__container'):
            texto.append(p.get_text(strip=True))
        texto_completo = "\n".join(texto)

        data_publicacao = None
        data_ultima_modificacao = None
        bloco_data = soup.find("p", class_="content-publication-data__updated")
        if bloco_data:
            t_pub = bloco_data.find("time", itemprop="datePublished")
            if t_pub and t_pub.has_attr('datetime'):
                data_publicacao = t_pub['datetime']
            t_mod = bloco_data.find("time", itemprop="dateModified")
            if t_mod and t_mod.has_attr('datetime'):
                data_ultima_modificacao = t_mod['datetime']

        return texto_completo, data_publicacao, data_ultima_modificacao
    except Exception as e:
        print(f"[detalhe] Erro ao acessar {url}:", e)
        return None, None, None

def gerar_id_hash(titulo, data_publicacao):
    valor = (titulo or "") + "|" + (data_publicacao or "")
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()

def coletar_noticias_completas():
    session = requests.Session()
    cookies = load_cookies_from_credentials()
    set_cookies_in_session(session, cookies)

    lista = get_noticias_list_page(session)
    hash_dict = {}
    for n in lista:
        if not n.get("link"):
            print("Notícia sem link, pulando:", n)
            continue
        print(f"Extraindo: {n['titulo']} | {n['link']}")
        texto, data_pub, data_mod = extrair_detalhe_noticia(session, n['link'])
        n["texto_completo"] = texto
        n["data_publicacao"] = data_pub
        n["data_ultima_modificacao"] = data_mod
        n["id_hash"] = gerar_id_hash(n["titulo"], data_pub)
        # Só salva se esse hash não existir ainda ou se for mais novo (data_publicacao maior)
        h = n["id_hash"]
        if h not in hash_dict:
            hash_dict[h] = n
        else:
            # Se já existe, mantém o mais recente
            old = hash_dict[h]
            def dtparse(val):
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    return datetime.min
            if dtparse(n["data_publicacao"]) > dtparse(old["data_publicacao"]):
                hash_dict[h] = n
    # Ordena pelas datas da mais recente para a mais antiga
    noticias_final = sorted(hash_dict.values(), key=lambda n: n["data_publicacao"] or "", reverse=True)
    return noticias_final

if __name__ == "__main__":
    noticias = coletar_noticias_completas()

    # Salva o resultado no JSON, ordenado
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(noticias, f, ensure_ascii=False, indent=2)

    print(f"\nArquivo '{OUTPUT_PATH}' salvo com {len(noticias)} notícias (ordenadas, ids únicos).\n")
