"""
Funções auxiliares para o BTG AlphaFeed.
Migrado de silva.py para arquitetura de API.
"""

import re
import os
import json
import hashlib
from typing import Any, Dict, Optional
import PyPDF2
from datetime import datetime, timezone, timedelta


def corrigir_tag_invalida(tag_original: str) -> str:
    """
    Mapeia tags inválidas ou similares para as tags válidas do TAGS_SPECIAL_SITUATIONS.
    
    Args:
        tag_original: Tag original que pode estar inválida
        
    Returns:
        Tag válida mapeada
    """
    if not tag_original or not isinstance(tag_original, str):
        return 'Internacional (Economia e Política)'  # Tag padrão das novas
    
    tag_limpa = tag_original.strip().lower()
    
    # Mapeamento de tags similares para as novas tags especializadas
    MAPEAMENTO_TAGS = {
        # Política Econômica (Brasil)
        'governo e politica': 'Política Econômica (Brasil)',
        'governo e política': 'Política Econômica (Brasil)', 
        'política': 'Política Econômica (Brasil)',
        'politica': 'Política Econômica (Brasil)',
        'governo': 'Política Econômica (Brasil)',
        'política econômica': 'Política Econômica (Brasil)',
        'politica economica': 'Política Econômica (Brasil)',
        'política pública': 'Política Econômica (Brasil)',
        'política publica': 'Política Econômica (Brasil)',
        
        # Internacional (Economia e Política)
        'economia e tecnologia': 'Internacional (Economia e Política)',
        'economia': 'Internacional (Economia e Política)',
        'tecnologia': 'Tecnologia e Setores Estratégicos',
        'tech': 'Tecnologia e Setores Estratégicos',
        'ia': 'Tecnologia e Setores Estratégicos',
        'inteligência artificial': 'Tecnologia e Setores Estratégicos',
        'inteligencia artificial': 'Tecnologia e Setores Estratégicos',
        'cripto': 'Internacional (Economia e Política)',
        'criptomoedas': 'Internacional (Economia e Política)',
        'bitcoin': 'Internacional (Economia e Política)',
        
        # Jurídico, Falências e Regulatório
        'judicionario': 'Jurídico, Falências e Regulatório',
        'judiciário': 'Jurídico, Falências e Regulatório',
        'judicial': 'Jurídico, Falências e Regulatório',
        'justiça': 'Jurídico, Falências e Regulatório',
        'justica': 'Jurídico, Falências e Regulatório',
        'tribunal': 'Jurídico, Falências e Regulatório',
        'stf': 'Jurídico, Falências e Regulatório',
        'stj': 'Jurídico, Falências e Regulatório',
        'supremo': 'Jurídico, Falências e Regulatório',
        'superior tribunal': 'Jurídico, Falências e Regulatório',
        'tj': 'Jurídico, Falências e Regulatório',
        'trf': 'Jurídico, Falências e Regulatório',
        'vara': 'Jurídico, Falências e Regulatório',
        'recuperação judicial': 'Jurídico, Falências e Regulatório',
        'recuperacao judicial': 'Jurídico, Falências e Regulatório',
        'falência': 'Jurídico, Falências e Regulatório',
        'falencia': 'Jurídico, Falências e Regulatório',
        'legislativo': 'Jurídico, Falências e Regulatório',
        'congresso': 'Jurídico, Falências e Regulatório',
        'senado': 'Jurídico, Falências e Regulatório',
        'câmara': 'Jurídico, Falências e Regulatório',
        'camara': 'Jurídico, Falências e Regulatório',
        
        # Mercado de Capitais e Finanças Corporativas
        'empresas privadas': 'Mercado de Capitais e Finanças Corporativas',
        'empresas': 'Mercado de Capitais e Finanças Corporativas',
        'corporativo': 'Mercado de Capitais e Finanças Corporativas',
        'negócios': 'Mercado de Capitais e Finanças Corporativas',
        'negocios': 'Mercado de Capitais e Finanças Corporativas',
        'mercado': 'Mercado de Capitais e Finanças Corporativas',
        'setor privado': 'Mercado de Capitais e Finanças Corporativas',
        
        # M&A e Transações Corporativas
        'm&a': 'M&A e Transações Corporativas',
        'fusão': 'M&A e Transações Corporativas',
        'fusao': 'M&A e Transações Corporativas',
        'aquisição': 'M&A e Transações Corporativas',
        'aquisicao': 'M&A e Transações Corporativas',
    }
    
    # Busca correspondência exata primeiro
    if tag_limpa in MAPEAMENTO_TAGS:
        return MAPEAMENTO_TAGS[tag_limpa]
    
    # Se não encontrar correspondência exata, busca por palavras-chave
    for palavra_chave, tag_correta in MAPEAMENTO_TAGS.items():
        if palavra_chave in tag_limpa:
            return tag_correta
    
    # Se nada corresponder, classifica como IRRELEVANTE
    return 'IRRELEVANTE'


def corrigir_prioridade_invalida(prioridade_original: Optional[str]) -> str:
    """
    Normaliza a prioridade. Se não for uma das válidas (P1_CRITICO, P2_ESTRATEGICO, P3_MONITORAMENTO),
    retorna 'IRRELEVANTE'.
    """
    validas = {'P1_CRITICO', 'P2_ESTRATEGICO', 'P3_MONITORAMENTO'}
    if isinstance(prioridade_original, str) and prioridade_original in validas:
        return prioridade_original
    return 'IRRELEVANTE'


def limpar_nome_arquivo(nome: str) -> str:
    """Remove caracteres especiais e limita o comprimento do nome do arquivo."""
    if not nome:
        return "arquivo_sem_nome"
    
    # Remove caracteres especiais, mantém apenas alphanumméricos, hífens, underscores e pontos
    nome = re.sub(r'[^\w\-_.]', '', nome)
    return nome[:150]


def extrair_json_da_resposta(resposta: str) -> Any:
    """
    Tenta extrair e decodificar um objeto JSON de uma string de resposta do LLM,
    que pode estar envolto em markdown, texto solto ou ser truncado.
    Inclui depuração detalhada em caso de falha.
    """
    # ETAPA 0: Validação inicial da resposta
    if not isinstance(resposta, str) or not resposta.strip():
        print("❌ Erro ao extrair JSON: A resposta recebida da API está vazia ou não é uma string.")
        return None

    json_str = ""
    # ETAPA 1: Tenta encontrar um bloco de código JSON explícito (```json ... ```)
    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', resposta, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        # ETAPA 2 (Fallback): Se não houver bloco de código, busca o primeiro '[' ou '{'
        start_bracket = resposta.find('[')
        start_brace = resposta.find('{')
        
        start = -1
        if start_bracket != -1 and (start_bracket < start_brace or start_brace == -1):
            start = start_bracket
        elif start_brace != -1:
            start = start_brace

        if start != -1:
            json_str = resposta[start:].strip()
        else:
            print("❌ Erro ao extrair JSON: Nenhum marcador de início ('[' ou '{') foi encontrado.")
            print("📋 RESPOSTA COMPLETA DA API (para depuração):")
            print("-" * 50)
            print(resposta)
            print("-" * 50)
            return None

    # ETAPA 3: Tenta decodificar o JSON extraído
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"❌ Erro ao decodificar JSON: {e}")
        print(f"📋 String que tentou decodificar:")
        print("-" * 50)
        print(json_str)
        print("-" * 50)
        return None


def verificar_dependencias():
    """
    Verifica se todas as dependências necessárias estão instaladas.
    """
    try:
        import google.generativeai as genai
        import PyPDF2
        import docx
        from sentence_transformers import SentenceTransformer
        import numpy as np
        import sqlalchemy
        print("✅ Todas as dependências estão disponíveis.")
        return True
    except ImportError as e:
        print(f"❌ Dependência faltando: {e}")
        print("Execute: pip install -r requirements.txt")
        return False


def contar_paginas_pdf(caminho_pdf: str) -> int:
    """
    Conta o número de páginas de um arquivo PDF.
    
    Args:
        caminho_pdf: Caminho para o arquivo PDF
        
    Returns:
        Número de páginas do PDF
    """
    try:
        with open(caminho_pdf, 'rb') as arquivo:
            leitor_pdf = PyPDF2.PdfReader(arquivo)
            return len(leitor_pdf.pages)
    except Exception as e:
        print(f"⚠️ Erro ao contar páginas do PDF {caminho_pdf}: {e}")
        return 0


def migrar_noticia_cache_legado(noticia_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Migra uma notícia do cache legado para o formato atual.
    Garante que todos os campos obrigatórios estejam presentes.
    
    Args:
        noticia_data: Dados da notícia no formato legado
        
    Returns:
        Dados da notícia no formato atual
    """
    # Campos obrigatórios com valores padrão
    campos_obrigatorios = {
        'titulo': noticia_data.get('titulo', ''),
        'texto_completo': noticia_data.get('texto_completo', ''),
        'jornal': noticia_data.get('jornal', 'N/A'),
        'autor': noticia_data.get('autor', 'N/A'),
        'pagina': noticia_data.get('pagina'),
        'data': noticia_data.get('data'),
        'categoria': noticia_data.get('categoria'),
        'tag': noticia_data.get('tag', 'Empresas Privadas'),
        'prioridade': noticia_data.get('prioridade', 'P3_MONITORAMENTO'),
        'relevance_score': noticia_data.get('relevance_score'),
        'relevance_reason': noticia_data.get('relevance_reason')
    }
    
    # Atualiza com os dados originais, mantendo os padrões se não existirem
    noticia_migrada = {**campos_obrigatorios, **noticia_data}
    
    # Corrige a tag se necessário
    noticia_migrada['tag'] = corrigir_tag_invalida(noticia_migrada['tag'])
    
    # Define relevance_reason padrão baseado na prioridade se não existir
    if not noticia_migrada.get('relevance_reason'):
        prioridade = noticia_migrada.get('prioridade', 'P3_MONITORAMENTO')
        noticia_migrada['relevance_reason'] = f"Migrado: Classificado como {prioridade}"
    
    return noticia_migrada


def gerar_hash_unico(texto: str, url: Optional[str] = None) -> str:
    """
    Gera um hash único para identificar artigos duplicados.
    
    Args:
        texto: Texto do artigo
        url: URL opcional do artigo
        
    Returns:
        Hash SHA256 do conteúdo
    """
    conteudo = f"{texto}{url or ''}"
    return hashlib.sha256(conteudo.encode('utf-8')).hexdigest()


def formatar_timestamp_relativo(timestamp_str: str) -> str:
    """
    Converte um timestamp para formato relativo (há X minutos/horas).
    
    Args:
        timestamp_str: Timestamp em formato ISO ou similar
        
    Returns:
        String no formato "há X minutos/horas"
    """
    from datetime import datetime, timezone
    
    try:
        # Tenta parsear diferentes formatos de timestamp
        if 'T' in timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        else:
            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        
        agora = datetime.now(timezone.utc)
        diferenca = agora - timestamp
        
        if diferenca.days > 0:
            return f"há {diferenca.days} dias"
        elif diferenca.seconds >= 3600:
            horas = diferenca.seconds // 3600
            return f"há {horas} horas"
        elif diferenca.seconds >= 60:
            minutos = diferenca.seconds // 60
            return f"há {minutos} minutos"
        else:
            return "há poucos segundos"
            
    except Exception:
        return "timestamp inválido"


def sanitizar_html(texto: str) -> str:
    """
    Remove tags HTML e caracteres especiais do texto.
    
    Args:
        texto: Texto com possíveis tags HTML
        
    Returns:
        Texto limpo
    """
    if not texto:
        return ""
    
    # Remove tags HTML
    texto_limpo = re.sub(r'<[^>]+>', '', texto)
    
    # Remove caracteres especiais e múltiplos espaços
    texto_limpo = re.sub(r'\s+', ' ', texto_limpo)
    
    return texto_limpo.strip()


def truncar_texto(texto: str, max_length: int = 500, sufixo: str = "...") -> str:
    """
    Trunca um texto para um comprimento máximo.
    
    Args:
        texto: Texto a ser truncado
        max_length: Comprimento máximo
        sufixo: Sufixo a ser adicionado se truncado
        
    Returns:
        Texto truncado
    """
    if not texto or len(texto) <= max_length:
        return texto
    
    return texto[:max_length - len(sufixo)] + sufixo


def get_gemini_model():
    """
    Configura e retorna o modelo Gemini para uso no chat.
    
    Returns:
        Modelo Gemini configurado
    """
    import os
    import google.generativeai as genai
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY não configurada")
    
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-2.0-flash-lite')

# ==============================================================================
# UTILITÁRIOS DE DATA E FUSO HORÁRIO (GMT-3)
# ==============================================================================

# Fuso horário de São Paulo/Brasília (GMT-3)
SAO_PAULO_TZ = timezone(timedelta(hours=-3))

def get_datetime_brasil() -> datetime:
    """
    Retorna datetime atual no fuso horário de São Paulo/Brasília (GMT-3).
    """
    return datetime.now(SAO_PAULO_TZ)

def get_date_brasil() -> datetime.date:
    """
    Retorna data atual no fuso horário de São Paulo/Brasília (GMT-3).
    """
    dt_brasil = get_datetime_brasil()
    return dt_brasil.date()

def get_datetime_brasil_str() -> str:
    """
    Retorna datetime atual como string ISO no fuso horário de São Paulo/Brasília.
    """
    return get_datetime_brasil().isoformat()

def get_date_brasil_str() -> str:
    """
    Retorna data atual como string YYYY-MM-DD no fuso horário de São Paulo/Brasília.
    """
    return get_date_brasil().strftime('%Y-%m-%d')

def convert_to_brasil_tz(dt: datetime) -> datetime:
    """
    Converte um datetime para o fuso horário de São Paulo/Brasília.
    Se o datetime não tem timezone, assume que é UTC.
    """
    if dt.tzinfo is None:
        # Assume UTC se não tem timezone
        dt = dt.replace(tzinfo=timezone.utc)
    
    return dt.astimezone(SAO_PAULO_TZ)

def format_datetime_brasil(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Formata um datetime para string no fuso horário de São Paulo/Brasília.
    """
    dt_brasil = convert_to_brasil_tz(dt)
    return dt_brasil.strftime(format_str)

def parse_date_brasil(date_str: str) -> datetime.date:
    """
    Converte string de data para objeto date, assumindo fuso horário de São Paulo.
    """
    try:
        # Tenta diferentes formatos
        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%Y-%m-%d %H:%M:%S']:
            try:
                dt = datetime.strptime(date_str, fmt)
                if fmt == '%Y-%m-%d':
                    return dt.date()
                else:
                    return convert_to_brasil_tz(dt).date()
            except ValueError:
                continue
        raise ValueError(f"Formato de data não reconhecido: {date_str}")
    except Exception as e:
        raise ValueError(f"Erro ao converter data '{date_str}': {e}")

def get_timestamp_brasil() -> str:
    """
    Retorna timestamp atual no formato YYYY-MM-DD_HHhMMm no fuso horário de São Paulo.
    """
    return get_datetime_brasil().strftime("%Y-%m-%d_%Hh%Mm")

def get_datetime_formatted_brasil() -> str:
    """
    Retorna datetime atual formatado como dd/mm/yyyy às HH:MM no fuso horário de São Paulo.
    """
    return get_datetime_brasil().strftime("%d/%m/%Y às %H:%M")