import json
import time

import requests
from bs4 import BeautifulSoup

# Desabilitar avisos de SSL para evitar poluição no console
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
from datetime import datetime, timedelta
import hashlib
from typing import List, Dict
from pathlib import Path
import pytz  # Para lidar com fuso horário

# --- Mapeamento dos Meses ---
meses = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

# Fuso horário local
timezone = pytz.timezone("America/Sao_Paulo")

# --- Utilitários ---

def filtrar_noticias_ultimas_24h(noticias: List[Dict]) -> List[Dict]:
    """
    Filtra as notícias cuja 'data_publicacao' esteja dentro das últimas 24 horas.

    Args:
        noticias (List[Dict]): Lista de dicionários com chave 'data_publicacao' no formato ISO 8601.

    Returns:
        List[Dict]: Lista de notícias publicadas nas últimas 24 horas.
    """
    agora = datetime.now(timezone)  # Data/hora atual com fuso horário local (aware)
    limite_inferior = agora - timedelta(hours=24)

    noticias_filtradas = []

    for noticia in noticias:
        data_str = noticia.get("data_publicacao")
        if data_str:
            try:
                data_publicacao = datetime.fromisoformat(data_str).astimezone(timezone)  # Torna a data 'aware'
                # Inclui se for dentro das últimas 24h ou mesmo dia
                if limite_inferior <= data_publicacao <= agora or data_publicacao.date() == agora.date():
                    noticias_filtradas.append(noticia)
            except ValueError:
                continue  # Ignora formatos inválidos

    return noticias_filtradas


def hash_noticia(titulo, data_publicacao):
    # Cria um hash único para cada notícia
    base = f"{titulo}|{data_publicacao}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


# Função para extrair as notícias da página
def get_news_list(page_number):
    url = f'https://www.migalhas.com.br/quentes?pagina={page_number}'
    response = requests.get(url, verify=False)
    time.sleep(0.5)

    if response.status_code != 200:
        print(f"Falha ao acessar a página {page_number}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    articles = soup.find_all('article', class_='item')

    news_list = []
    for article in articles:
        news = {}

        # Captura o link da notícia
        link = article.find('a', href=True)
        news['link'] = link['href']

        # Captura o título da notícia
        news['titulo'] = link.get('title', '')

        # Gerar hash_id único
        news['id_hash'] = hash_noticia(news['titulo'], news.get("date"))

        # # Captura a data da notícia
        # date_span = article.find('span', class_='badge badge--vermelho')
        # news['date'] = date_span.get_text(strip=True) if date_span else None

        # Captura o resumo da notícia
        summary = article.find('h3', class_='topico__body')
        news['subtitulo'] = summary.get_text(strip=True) if summary else ''

        news_list.append(news)

    return news_list


# Função para extrair o conteúdo completo de uma notícia
def get_news_content(news_url):
    response = requests.get(news_url, verify=False)

    if response.status_code != 200:
        print(f"Falha ao acessar a notícia: {news_url}")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')

    # Captura o primeiro <div> com a classe 'noticia' e pega todos os <p> dentro dele
    noticia_div = soup.find('div', class_='noticia')

    if noticia_div:
        paragraphs = noticia_div.find_all('p')  # Encontrar todos os <p> dentro do primeiro <div class="noticia">
        content = '\n'.join([p.get_text(strip=True) for p in paragraphs])
    else:
        print(f"Não foi encontrado o <div> com a classe 'noticia' em: {news_url}")
        content = ""

    # Captura a data e hora da publicação
    date_section = soup.find('div', class_='topico__data')
    date_text = date_section.find_all('p') if date_section else []
    publication_date = date_text[1].get_text(strip=True) if len(date_text) > 1 else 'Data não disponível'
    publication_time = date_text[2].get_text(strip=True) if len(date_text) > 2 else 'Hora não disponível'

    # Converte data e hora para o formato ISO 8601
    try:
        # Formato da data: terça-feira, 5 de agosto de 2025
        data_parts = publication_date.split(', ')
        data = data_parts[1]  # Ex: '5 de agosto de 2025'

        # Extraindo o dia, mês e ano
        dia, mes, ano = data.split(' de ')

        # Usando o mapeamento para o número do mês
        mes_numero = meses.get(mes.lower(), None)
        if mes_numero:
            data_formatada = f"{ano}-{str(mes_numero).zfill(2)}-{str(int(dia)).zfill(2)}"
        else:
            data_formatada = 'Data inválida'

        # Adicionando a hora de publicação
        hora_parts = publication_time.split(' às ')
        if len(hora_parts) > 1:
            hora = hora_parts[1].split(':')
            data_formatada = f"{data_formatada}T{hora[0]}:{hora[1]}:00Z"

        # Convertendo para uma data "aware" com o fuso horário
        publication_date_obj = datetime.fromisoformat(data_formatada).astimezone(timezone)

        return {
            'content': content,
            'data_publicacao': publication_date_obj.isoformat(),  # ISO 8601
            'data_ultima_modificacao': publication_date_obj.isoformat()  # A data de modificação é a mesma da publicação
        }

    except Exception as e:
        print(f"Erro ao converter data: {e}")
        return {
            'content': content,
            'data_publicacao': 'Data não disponível',
            'data_ultima_modificacao': 'Data não disponível'
        }


def remover_antes_da_substring(texto, substring="Atualizado às"):
    """
    Remove tudo antes e inclusive a substring especificada da string fornecida.

    Args:
        texto (str): A string onde a operação será realizada.
        substring (str): A substring que será usada como ponto de corte.

    Returns:
        str: A string resultante após a remoção da parte anterior à substring.
    """
    # Localiza a posição da substring
    posicao = texto.find(substring)

    # Se a substring for encontrada, remove tudo antes dela, inclusive ela
    if posicao != -1:
        return texto[posicao + len(substring) + 7:].replace('\n', '').strip()  # Remove a substring e qualquer espaço extra
    return texto.replace('\n', '').strip()  # Caso a substring não seja encontrada, retorna o texto original


# Função principal para processar as notícias
def scrape_migalhas():
    all_news = []

    n_pages = 5

    for page in range(1, n_pages + 1):  # Para pegar as 'n_pages' primeiras páginas de notícias
        print(f"Coletando notícias da página {page}...")
        time.sleep(1)
        news_list = get_news_list(page)

        for news in news_list:
            print(f"Coletando conteúdo da notícia: {news['titulo']}")
            news_content = get_news_content(news['link'])

            if news_content:
                # Aplicando a remoção do conteúdo antes de "Atualizado às"
                texto_completo_processado = remover_antes_da_substring(news_content['content'])

                # Salvando os dados no formato esperado
                news['texto_completo'] = texto_completo_processado
                news['data_publicacao'] = news_content['data_publicacao']
                news['data_ultima_modificacao'] = news_content['data_ultima_modificacao']
                news['tags'] = []
                news['fonte'] = 'Migalhas'

            all_news.append(news)

    # Filtra as notícias das últimas 24 horas
    filtered_news = filtrar_noticias_ultimas_24h(all_news)

    return filtered_news, all_news


# Função para salvar os dados em um arquivo .json
def save_to_json(data, output_dir, filename):
    if not Path(output_dir).exists():
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    output_path = Path(output_dir) / filename
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"Dados salvos em {output_path}")


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

    # Coletar as notícias
    noticias_24h, noticias_todas = scrape_migalhas()

    # Salvar todas as notícias localizadas
    save_to_json(noticias_todas, OUTPUT_DIR_TODAS, "noticias_migalhas_paginated.json")
    print(f"\nTotal de notícias salvas: {len(noticias_todas)}")

    # Salvar últimas 24h em diretório separado
    save_to_json(noticias_24h, OUTPUT_DIR_24H, "noticias_migalhas_ultimas_24h.json")
    print(f"\nTotal de notícias nas últimas 24h: {len(noticias_24h)}")
