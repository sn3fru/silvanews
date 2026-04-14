"""
Funções auxiliares para o BTG AlphaFeed.
Migrado de silva.py para arquitetura de API.
"""

import re
import os
import json
import hashlib
import unicodedata
from typing import Any, Dict, List, Optional
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


def eh_lixo_publicitario(titulo: Optional[str], texto: Optional[str]) -> bool:
    """
    Heurística simples para detectar conteúdo publicitário/anúncio e descartar cedo.
    Retorna True quando o texto aparenta ser anúncio, promoção ou comunicados comerciais
    sem materialidade noticiosa.

    Critérios (qualquer um):
    - Palavras-chave típicas de anúncio/promo
    - Presença de faixas de horário e local típicos de evento (ex.: "10h às 12h", endereço)
    - Muitos padrões de preço/contato (R$, WhatsApp, telefone)
    - Termos de supermercado/loja, cupom, desconto
    """
    try:
        conteudo = f"{titulo or ''}\n{texto or ''}".lower()

        # Palavras-chave comuns em anúncios
        palavras = [
            r"anúncio", r"anuncio", r"publicitário", r"publicitario", r"promoção", r"promocao",
            r"oferta", r"imperdível", r"imperdivel", r"liquidação", r"liquidacao", r"cupom",
            r"desconto", r"brinde", r"compre", r"ingressos", r"ingresso", r"cadastre-se",
            r"cadastre se", r"inscreva-se", r"inscreva se", r"patrocinado", r"publi"
        ]

        # Setores muito associados a varejo/mercado quando em tom promocional
        varejo = [
            r"supermarket", r"supermercado", r"hipermercado", r"loja", r"shopping",
            r"farmácia", r"farmacia", r"eletro", r"móveis", r"moveis"
        ]

        # Padrões de horário e local típico de evento/ação
        padroes_regex = [
            r"\b\d{1,2}h\s*(às|as)\s*\d{1,2}h\b",
            r"\b(?:r\.|rua|av\.|avenida|praça|praca|centro|shopping)\b",
            r"\bwhatsapp\b",
            r"\b(?:\(\d{2}\)\s*\d{4,5}-\d{4})\b",
            r"\br\$\s*\d+[\.\d]*\b"
        ]

        # Se encontrar palavras-chave fortes de anúncio
        if any(re.search(rf"\b{p}\b", conteudo) for p in palavras):
            return True

        # Se houver forte presença de varejo + preço/telefone/whatsapp
        sinais_varejo = any(v in conteudo for v in varejo)
        sinais_contato_preco = sum(1 for rgx in padroes_regex if re.search(rgx, conteudo))
        if sinais_varejo and sinais_contato_preco >= 1:
            return True

        # Se houver múltiplos sinais de contato/preço/horário mesmo sem varejo explícito
        if sinais_contato_preco >= 2:
            return True

        return False
    except Exception:
        # Em caso de erro na heurística, não bloquear
        return False


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
    import logging
    logger = logging.getLogger(__name__)

    # ETAPA 0: Validação inicial da resposta
    if not isinstance(resposta, str) or not resposta.strip():
        logger.error("❌ Erro ao extrair JSON: A resposta recebida da API está vazia ou não é uma string.")
        return None

    logger.debug(f"🔍 Processando resposta do LLM (comprimento: {len(resposta)} chars)")

    json_str = ""

    # ETAPA 1: Primeiro tenta encontrar JSON puro sem markdown
    # Procura por {"chave": "valor"} ou similares
    json_pattern = r'\{[^{}]*"resumo_expandido"[^{}]*\}'
    match = re.search(json_pattern, resposta, re.DOTALL)
    if match:
        json_str = match.group(0).strip()
        logger.debug("✅ Encontrou JSON puro na resposta")
    else:
        # ETAPA 2: Tenta encontrar um bloco de código JSON explícito (```json ... ```)
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', resposta, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            logger.debug("✅ Encontrou bloco JSON markdown na resposta")
        else:
            # ETAPA 3 (Fallback): Se não houver bloco de código, busca o primeiro '{'
            start_brace = resposta.find('{')
            if start_brace != -1:
                # Procura pelo fim do objeto JSON (conta chaves)
                json_str = resposta[start_brace:].strip()
                logger.debug("✅ Usando fallback - procurando '{' na resposta")
            else:
                logger.error("❌ Erro ao extrair JSON: Nenhum marcador de início ('{') foi encontrado.")
                logger.error("📋 RESPOSTA COMPLETA DA API (para depuração):")
                logger.error("-" * 50)
                logger.error(resposta)
                logger.error("-" * 50)
                return None

    # ETAPA 4: Limpa a string JSON (remove caracteres extras)
    json_str = json_str.strip()

    # Remove caracteres estranhos no início/fim se houver
    if json_str.startswith('```'):
        json_str = json_str[3:]
    if json_str.endswith('```'):
        json_str = json_str[:-3]
    json_str = json_str.strip()

    # ETAPA 5: Tenta decodificar o JSON extraído
    try:
        parsed = json.loads(json_str)
        logger.debug("✅ JSON decodificado com sucesso")
        return parsed
    except json.JSONDecodeError as e:
        logger.error(f"❌ Erro ao decodificar JSON: {e}")
        logger.error("📋 String que tentou decodificar:")
        logger.error("-" * 50)
        logger.error(repr(json_str))  # Usando repr para mostrar caracteres especiais
        logger.error("-" * 50)

        # TENTA 6: Último recurso - tenta corrigir problemas comuns
        try:
            # Remove aspas simples incorretas e substitui por duplas
            corrected = json_str.replace("'", '"')
            parsed = json.loads(corrected)
            logger.warning("⚠️ JSON corrigido automaticamente (aspas simples -> duplas)")
            return parsed
        except:
            logger.error("❌ Falha mesmo na correção automática")
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


def gerar_titulo_fallback_curto(texto: Optional[str], max_palavras: int = 10) -> str:
    """
    Gera um título curto e determinístico a partir do texto completo quando o título está ausente.
    - Usa a primeira sentença não vazia; se indisponível, usa as primeiras N palavras
    - Normaliza espaços e remove URLs
    - Retorna "Sem título" apenas como último recurso
    """
    try:
        if not isinstance(texto, str):
            return "Sem título"
        conteudo = (texto or "").strip()
        if not conteudo:
            return "Sem título"
        # Remove URLs e excesso de espaços
        conteudo = re.sub(r"https?://\S+", " ", conteudo)
        conteudo = re.sub(r"\s+", " ", conteudo).strip()
        # Tenta primeira sentença
        sentencas = re.split(r"(?<=[\.!?])\s+", conteudo)
        primeira = next((s for s in sentencas if s and len(s.strip()) > 0), conteudo)
        # Se muito longa, reduz para N palavras
        palavras = primeira.split()
        if len(palavras) > max_palavras:
            primeira = " ".join(palavras[:max_palavras])
        # Sanitiza trailing pontuação pesada
        primeira = primeira.strip(" -—:;,")
        return primeira if primeira else "Sem título"
    except Exception:
        return "Sem título"


def titulo_e_generico(titulo: Optional[str]) -> bool:
    """
    Detecta títulos genéricos que não devem ser usados para agrupar/mesclar (ex.: "Sem título").
    """
    if not isinstance(titulo, str):
        return True
    t = titulo.strip().lower()
    if not t:
        return True
    padroes = [
        "sem título", "sem titulo", "notícia sem título", "noticias sem titulo",
        "novo cluster", "grupo lote",
    ]
    return any(t.startswith(p) for p in padroes)


# Fontes que emitem updates fragmentados (flashes). Para estas, a heurística "mesmo jornal"
# aplica-se com prompt MAIS RIGOROSO (não isenção): só agrupar se Entidade e Ação forem
# exatamente continuação do fato anterior. Usado em agrupamento (docs/GUIA_IMPLEMENTACAO_AGRUPAMENTO_PRIORIZACAO.md).
FONTES_FLASHES: List[str] = [
    "valor economico",
    "valor pro",
    "valor economico pro",
    "bloomberg",
    "reuters",
]


def normalizar_jornal(nome: Optional[str]) -> str:
    """
    Normaliza o nome do jornal para chave canônica (lowercase, sem acentos, aliases mapeados).
    Usado pela heurística da fonte no agrupamento: mesmo jornal no cluster exige critério mais rigoroso.
    """
    if not nome or not isinstance(nome, str):
        return ""
    s = nome.strip()
    if not s:
        return ""
    # Remove acentos (NFKD + remove combining chars)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.lower()
    # Normaliza separadores e espaços
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Aliases para chave canônica (evita "o estado de s. paulo" vs "estadao" diferentes)
    ALIASES_JORNAL = {
        "o estado de s paulo": "estadao",
        "estado de s paulo": "estadao",
        "estadao": "estadao",
        "estadão": "estadao",
        "valor economico": "valor economico",
        "valor": "valor economico",
        "valor pro": "valor economico",
        "valor economico pro": "valor economico",
        "brazil journal": "brazil journal",
        "folha de s paulo": "folha",
        "folha": "folha",
        "exame": "exame",
        "infomoney": "infomoney",
        "investing": "investing",
    }
    return ALIASES_JORNAL.get(s, s)


_FONTE_DISPLAY_MAP = {
    "estadao": "O Estado de S.Paulo",
    "o estado de s paulo": "O Estado de S.Paulo",
    "estado de s paulo": "O Estado de S.Paulo",
    "valor economico": "Valor Econômico",
    "valor": "Valor Econômico",
    "valor pro": "Valor Econômico",
    "folha": "Folha de S.Paulo",
    "folha de s paulo": "Folha de S.Paulo",
    "brazil journal": "Brazil Journal",
    "exame": "Exame",
    "infomoney": "InfoMoney",
    "investing": "Investing.com",
    "bloomberg": "Bloomberg",
    "reuters": "Reuters",
    "financial times": "Financial Times",
    "conjur": "Conjur",
    "jota": "JOTA",
    "migalhas": "Migalhas",
    "neofeed": "NeoFeed",
    "pipeline": "Pipeline Valor",
    "capital aberto": "Capital Aberto",
    "o globo": "O Globo",
    "gazeta": "Gazeta do Povo",
    "correio braziliense": "Correio Braziliense",
    "broadcast": "Broadcast",
    "reset": "Reset",
    "wall street journal": "The Wall Street Journal",
    "wsj": "The Wall Street Journal",
    "new york times": "The New York Times",
    "nyt": "The New York Times",
}

_FONTE_LIXO_PATTERNS = re.compile(
    r"^[a-z0-9_]{2,20}$"   # parece username (ex: "ines249", "user_abc")
    r"|^json.?dump$"
    r"|^fonte.?desconhecida$"
    r"|^n/?a$"
    r"|^sem.?fonte$"
    r"|^unknown$"
    r"|^dump.?crawlers"      # dump_crawlers_20260317 etc.
    r"|^noticias_.+_paginated$"  # noticias_valor_paginated etc.
    r"|^noticias_.+_ultimas",    # noticias_jota_ultimas_24h etc.
    re.IGNORECASE,
)


def normalizar_fonte_display(nome: Optional[str]) -> str:
    """
    Retorna o nome de exibicao limpo e padronizado de uma fonte.
    Ex: "SP O Estado de S Paulo - 150326" -> "O Estado de S.Paulo"
        "ines249" -> "" (lixo, ignorado)
        "Valor Econômico" -> "Valor Econômico"
    """
    if not nome or not isinstance(nome, str):
        return ""
    s = nome.strip()
    if not s:
        return ""

    if _FONTE_LIXO_PATTERNS.match(s):
        return ""

    chave = normalizar_jornal(s)
    if chave in _FONTE_DISPLAY_MAP:
        return _FONTE_DISPLAY_MAP[chave]

    for keyword, display in _FONTE_DISPLAY_MAP.items():
        if keyword in s.lower():
            return display

    if len(s) < 3 or s.replace(" ", "").isdigit():
        return ""

    return s.strip()


def inferir_tipo_fonte_por_jornal(nome_jornal: Optional[str]) -> str:
    """
    Inferência heurística de tipo de fonte ('nacional' ou 'internacional') a partir do nome do jornal.
    - Usa listas ampliadas de substrings; tolera siglas e nomes parciais (ex.: 'FT', 'WSJ').
    - Default: 'nacional'.
    """
    try:
        if not isinstance(nome_jornal, str) or not nome_jornal.strip():
            return 'nacional'
        s = nome_jornal.strip().lower()
        # Normaliza separadores incomuns (underscores, hífens, múltiplos espaços)
        try:
            import re as _re
            s_norm = _re.sub(r"[^a-z0-9]+", " ", s)
            s_norm = _re.sub(r"\s+", " ", s_norm).strip()
        except Exception:
            s_norm = s
        internacionais = [
            'financial times', 'ft ', ' ft', 'ft.com', 'ft weekend', 'ftweekend',
            'bloomberg', 'reuters', 'associated press', 'ap ', 'ap news',
            'wall street journal', 'wsj',
            'new york times', 'nyt', 'washington post', 'wapo',
            'the guardian', 'guardian', 'bbc', 'cnn', 'cnbc', 'the economist',
            'forbes', 'marketwatch', 'barron', "barron's", 'the telegraph',
            'the times', 'usa today', 'los angeles times', 'la times',
            'chicago tribune', 'axios', 'politico', 'the hill',
            'nikkei', 'japan times', 'south china morning post', 'scmp',
            'al jazeera', 'sky news', 'the hindu', 'times of india',
        ]
        # Checa contra ambas as versões (original e normalizada)
        if any((k in s) or (k in s_norm) for k in internacionais):
            return 'internacional'
        return 'nacional'
    except Exception:
        return 'nacional'


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
    # Usa o modelo Pro (mais capaz) especificamente para o chat do modal
    return genai.GenerativeModel('gemini-3-flash-preview')

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