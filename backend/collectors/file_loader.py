"""
Coletor de arquivos para o BTG AlphaFeed.
Carrega notícias a partir de arquivos PDFs (com extração via IA) e JSONs.
"""

import os
import json
import hashlib
import time
import tempfile
import re
from typing import Dict, Any, List, Optional
from pathlib import Path
import requests
import concurrent.futures

try:
    import fitz  # PyMuPDF
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# Importações do projeto com suporte a execução como pacote ou script
try:
    from ..database import SessionLocal
    from ..models import ArtigoBrutoCreate
    from ..crud import create_artigo_bruto, get_artigo_by_hash, create_log
    from ..prompts import PROMPT_EXTRACAO_PDF_RAW_V1
    from ..utils import get_datetime_brasil_str, get_date_brasil_str, gerar_titulo_fallback_curto, titulo_e_generico, inferir_tipo_fonte_por_jornal
except ImportError:
    # Fallback para execução direta
    try:
        from database import SessionLocal
        from models import ArtigoBrutoCreate
        from crud import create_artigo_bruto, get_artigo_by_hash, create_log
        from prompts import PROMPT_EXTRACAO_PDF_RAW_V1
        from utils import get_datetime_brasil_str, get_date_brasil_str, gerar_titulo_fallback_curto, titulo_e_generico, inferir_tipo_fonte_por_jornal
    except ImportError as e:
        print(f"❌ ERRO: Não foi possível importar módulos do backend: {e}")
        print(f"   Verifique se está executando a partir do diretório correto")
        raise

# Constantes para o processamento de PDF, para garantir robustez.
PAGINAS_POR_CHUNK = 5
LIMITE_PAGINAS_CHUNKING = 10  # Um limite mais baixo é mais seguro para PDFs densos

class FileLoader:
    """
    Coletor refatorado para processar arquivos de forma robusta.
    - Utiliza a File API do Gemini para OCR e extração de notícias de PDFs.
    - Implementa 'chunking' para PDFs grandes, evitando timeouts da API.
    - Processa JSONs de forma eficiente.
    - Interage com a API do backend ou diretamente com o banco de dados.
    """

    def __init__(self, api_base_url: str = "http://localhost:8000",
                 files_directory: str = "../pdfs", client: Any = None):
        self.api_base_url = api_base_url
        self.files_directory = Path(files_directory)
        self.session = requests.Session()
        
        # Injeção de dependência: o cliente Gemini é recebido aqui.
        # Isso centraliza a configuração e torna a classe mais testável.
        self.client = client
        self.extraction_prompt = PROMPT_EXTRACAO_PDF_RAW_V1
        # Config padrão para tarefas de decisão (alinhado ao poc_silva)
        self.generation_config_decision = {
            "temperature": 0.1,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 65536,
        }

        if not self.files_directory.exists():
            raise FileNotFoundError(f"ERRO: Diretório de origem não encontrado: {self.files_directory}")
        if PDF_AVAILABLE and not self.client:
            print("⚠️ AVISO: Cliente Gemini não foi fornecido. O processamento de PDFs usará extração de texto simples, sem IA.")

    def gerar_hash_artigo(self, texto: str, url: str = "") -> str:
        """Gera hash único para o artigo."""
        conteudo = f"{texto}{url if url else ''}"
        return hashlib.sha256(conteudo.encode('utf-8')).hexdigest()
    
    def detectar_tipo_fonte(self, jornal: str) -> str:
        """
        OBSOLETA: Mantida para compatibilidade. Use detectar_tipo_fonte_completo().
        Detecta se um jornal é nacional ou internacional baseado no nome.
        """
        return self.detectar_tipo_fonte_completo(jornal, tem_url=False, tipo_arquivo='pdf')
    
    def detectar_tipo_fonte_completo(self, jornal: str, tem_url: bool = False, tipo_arquivo: str = 'pdf') -> str:
        """
        Detecta o tipo de fonte considerando três categorias:
        - 'brasil_fisico': PDFs de jornais brasileiros (jornais impressos)
        - 'brasil_online': JSONs com URL de sites brasileiros 
        - 'internacional': Qualquer fonte estrangeira (PDF ou JSON)
        
        Args:
            jornal: Nome do jornal/fonte
            tem_url: Se True, indica que é uma notícia online (JSON com link)
            tipo_arquivo: 'pdf' ou 'json'
        """
        jornais_nacionais = {
            'folha', 'folha de s. paulo', 'folha de são paulo', 'folha de s.paulo',
            'estadao', 'estadão', 'estado de s. paulo', 'estado de são paulo', 'o estado de s. paulo',
            'globo', 'o globo', 'g1', 'valor', 'valor economico', 'valor econômico',
            'uol', 'r7', 'veja', 'exame', 'istoé', 'istoe', 'época', 'epoca',
            'correio braziliense', 'correio', 'zero hora', 'gazeta do povo',
            'metrópoles', 'metropoles', 'poder360', 'infomoney', 'investing.com brasil',
            'brasil 247', 'carta capital', 'cartacapital', 'agência brasil', 'agencia brasil',
            'bbc brasil', 'cnn brasil', 'diário do comércio', 'diario do comercio',
            'dci', 'monitor mercantil', 'brazil journal', 'jota', 'conjur',
            'consultor jurídico', 'migalhas', 'capital reset', 'neo feed', 'neofeed',
            'brazil journal', 'the brazilian report'
        }
        
        jornais_internacionais = {
            'new york times', 'nyt', 'wall street journal', 'wsj', 'financial times', 'ft',
            'bloomberg', 'reuters', 'associated press', 'ap', 'washington post',
            'the guardian', 'bbc', 'cnn', 'cnbc', 'the economist', 'forbes',
            'business insider', 'marketwatch', 'barrons', 'barron\'s', 'the telegraph',
            'the times', 'daily mail', 'usa today', 'los angeles times', 'chicago tribune',
            'boston globe', 'miami herald', 'axios', 'politico', 'the hill',
            'foreign policy', 'foreign affairs', 'the atlantic', 'vox', 'vice',
            'buzzfeed', 'huffpost', 'huffington post', 'daily beast', 'slate',
            'salon', 'mother jones', 'the intercept', 'propublica', 'npr',
            'pbs', 'abc news', 'nbc news', 'cbs news', 'fox news', 'msnbc',
            'sky news', 'al jazeera', 'russia today', 'rt', 'sputnik',
            'china daily', 'xinhua', 'nikkei', 'japan times', 'korea herald',
            'south china morning post', 'scmp', 'the hindu', 'times of india',
            'dawn', 'the nation', 'jerusalem post', 'haaretz', 'al arabiya',
            'gulf news', 'arab news', 'the national', 'daily star', 'the star'
        }
        
        if not jornal:
            # Default baseado no tipo de arquivo
            return 'brasil_fisico' if tipo_arquivo == 'pdf' else 'brasil_online'
        
        jornal_lower = jornal.lower().strip()
        
        # Verifica se é internacional (prioridade mais alta)
        for nome in jornais_internacionais:
            if nome in jornal_lower:
                return 'internacional'
        
        # Verifica se é nacional brasileiro
        is_nacional = False
        for nome in jornais_nacionais:
            if nome in jornal_lower:
                is_nacional = True
                break
        
        # Se tem .br no nome ou palavras-chave brasileiras, também é nacional
        if not is_nacional:
            if '.br' in jornal_lower or 'brasil' in jornal_lower or 'brazil' in jornal_lower:
                is_nacional = True
        
        if is_nacional:
            # Se é nacional, diferencia por tipo de fonte
            if tipo_arquivo == 'pdf' or not tem_url:
                return 'brasil_fisico'  # PDF = impresso/físico
            else:
                return 'brasil_online'   # JSON com URL = online
        
        # Se não identificou como nacional nem internacional, usa heurística:
        # - PDFs sem identificação clara: brasil_fisico (compatibilidade)
        # - JSONs com URL: internacional (assume fonte estrangeira)
        if tipo_arquivo == 'pdf':
            return 'brasil_fisico'
        else:
            return 'internacional' if tem_url else 'brasil_online'

    # Heurística leve de idioma: detecta se o texto está majoritariamente em PT-BR
    def _texto_e_portugues(self, texto: Optional[str]) -> bool:
        try:
            if not isinstance(texto, str) or len(texto) < 40:
                # Texto muito curto: presume PT para segurança (evita falso internacional)
                return True
            s = texto.lower()
            # Conjunto enxuto de stopwords/frequentes do PT
            termos_pt = [
                ' de ', ' do ', ' da ', ' dos ', ' das ', ' que ', ' em ', ' para ', ' por ', ' com ',
                ' não ', ' ao ', ' aos ', ' aos ', ' uma ', ' sua ', ' seu ', ' seus ', ' suas ',
                ' é ', ' foi ', ' são ', ' estar ', ' como ', ' sobre ', ' entre ', ' contra ', ' pela ', ' pelas '
            ]
            acentos = any(ch in s for ch in 'áàâãéêíóôõúç')
            hits = sum(1 for t in termos_pt if t in s)
            densidade = hits / max(1, len(s) / 500)  # escala com tamanho
            return acentos or densidade >= 1.0
        except Exception:
            return True

    def inferir_tipo_por_texto(self, texto: Optional[str], tipo_arquivo: str, tem_url: bool) -> str:
        # Internacional se claramente não PT; caso contrário decide entre físico/online
        if not self._texto_e_portugues(texto):
            return 'internacional'
        return 'brasil_fisico' if tipo_arquivo == 'pdf' or not tem_url else 'brasil_online'

    # --- LÓGICA DE PROCESSAMENTO DE PDF (REFATORADA) ---

    def _extrair_json_da_resposta(self, resposta: str, contexto: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Extrai, higieniza e decodifica JSON retornado por LLMs de forma robusta.
        - Remove blocos markdown
        - Tenta parse direto
        - Fallback para extração campo-a-campo via regex
        """
        if not isinstance(resposta, str) or not resposta.strip():
            print("  ❌ Resposta da API vazia.")
            return []

        # Remove blocos markdown primeiro (mais agressivo)
        json_str = resposta
        # Remove múltiplas variações de blocos markdown
        json_str = re.sub(r'```(?:json|JSON|Json)?\s*\n?', '', json_str)
        json_str = re.sub(r'```\s*$', '', json_str)
        
        # Se ainda tem marcadores, tenta extrair conteúdo entre eles
        match = re.search(r'```(?:json|JSON|Json)?\s*([\s\S]*?)\s*```', resposta, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
        
        # Tenta parse direto primeiro (para respostas bem formadas)
        try:
            dados = json.loads(json_str)
            if isinstance(dados, list):
                return dados
            if isinstance(dados, dict):
                return [dados]
        except:
            pass  # Continua com sanitização

        # Se falhou, tenta extração campo-a-campo via regex
        artigos_extraidos = []
        
        # Pattern para encontrar notícias individuais
        # Busca por objetos que tenham pelo menos titulo e texto_completo
        pattern = re.compile(
            r'\{[^{}]*?"titulo"\s*:\s*"((?:[^"]|(?<=\\)")*?)"[^{}]*?"texto_completo"\s*:\s*"((?:[^"]|(?<=\\)")*?)"[^{}]*?\}',
            re.DOTALL
        )
        
        for match in pattern.finditer(json_str):
            titulo_raw = match.group(1)
            texto_raw = match.group(2)
            
            # Limpa os campos extraídos
            titulo = titulo_raw.replace('\\"', '"').replace('\\n', ' ').replace('\n', ' ').strip()
            texto = texto_raw.replace('\\"', '"').replace('\\n', ' ').replace('\n', ' ').strip()
            
            if titulo and texto:
                # Tenta extrair outros campos do objeto
                obj_str = match.group(0)
                
                # Extrai campos opcionais - mais tolerante com valores numéricos
                def extract_field(field_name: str, obj: str) -> Optional[str]:
                    # Tenta string entre aspas
                    pat = re.compile(rf'"{field_name}"\s*:\s*"((?:[^"]|(?<=\\)")*?)"')
                    m = pat.search(obj)
                    if m:
                        return m.group(1).replace('\\"', '"').replace('\\n', ' ').replace('\n', ' ').strip()
                    
                    # Tenta valor numérico (para pagina)
                    pat_num = re.compile(rf'"{field_name}"\s*:\s*(\d+)')
                    m_num = pat_num.search(obj)
                    if m_num:
                        return m_num.group(1)
                    
                    # Tenta null/None
                    pat_null = re.compile(rf'"{field_name}"\s*:\s*(?:null|None)')
                    if pat_null.search(obj):
                        return None
                    return None
                
                artigos_extraidos.append({
                    'titulo': titulo,
                    'texto_completo': texto,
                    'jornal': extract_field('jornal', obj_str),
                    'autor': extract_field('autor', obj_str),
                    'pagina': extract_field('pagina', obj_str),
                    'data': extract_field('data', obj_str),
                    'categoria': extract_field('categoria', obj_str),
                    'tag': extract_field('tag', obj_str),
                    'prioridade': extract_field('prioridade', obj_str),
                    'relevance_score': extract_field('relevance_score', obj_str),
                    'relevance_reason': extract_field('relevance_reason', obj_str)
                })
        
        if artigos_extraidos:
            return artigos_extraidos
        
        # Se ainda não conseguiu, tenta sanitização mais agressiva
        print("  🔧 Tentando sanitização avançada do JSON...")
        
        # Pré-correções comuns antes do parse
        try:
            # Função auxiliar para sanitizar campos string
            def _sanitize_string_fields(s: str, fields: List[str]) -> str:
                out_parts: List[str] = []
                pos = 0
                pattern = re.compile(r'("(?:' + '|'.join(re.escape(f) for f in fields) + r')"\s*:\s*")')
                while True:
                    m = pattern.search(s, pos)
                    if not m:
                        out_parts.append(s[pos:])
                        break
                    # adiciona trecho antes do campo
                    out_parts.append(s[pos:m.end()])
                    i = m.end()  # início do conteúdo dentro das aspas
                    buf_chars: List[str] = []
                    while i < len(s):
                        ch = s[i]
                        if ch == '\\':
                            # mantém escapes já existentes, mas normaliza \n, \r, \t para espaço
                            if i + 1 < len(s) and s[i+1] in ('n', 'r', 't'):
                                buf_chars.append(' ')
                                i += 2
                                continue
                            # trata sequência barra + quebra real (\\\n ou \\\r)
                            if i + 1 < len(s) and s[i+1] in ('\n', '\r'):
                                buf_chars.append(' ')
                                i += 2
                                continue
                            # mantém escape para outros casos
                            if i + 1 < len(s):
                                buf_chars.append('\\')
                                buf_chars.append(s[i+1])
                                i += 2
                                continue
                            buf_chars.append('\\')
                            i += 1
                            continue
                        if ch == '"':
                            # olha adiante para decidir se é fechamento (seguido de , ou })
                            j = i + 1
                            while j < len(s) and s[j] in (' ', '\n', '\r', '\t'):
                                j += 1
                            if j < len(s) and s[j] in (',', '}'):
                                # fecha string
                                out_parts.append(''.join(buf_chars))
                                out_parts.append('"')
                                pos = i + 1
                                break
                            # aspa interna não escapada → escapa
                            buf_chars.append('\\"')
                            i += 1
                            continue
                        if ch in ('\n', '\r'):
                            buf_chars.append(' ')
                            i += 1
                            continue
                        buf_chars.append(ch)
                        i += 1
                    else:
                        # EOF sem fechamento; adiciona buffer e encerra
                        out_parts.append(''.join(buf_chars))
                        pos = i
                        break
                # Colapsa espaços excessivos dentro dos campos já sanitizados
                result = ''.join(out_parts)
                return result

            json_str = _sanitize_string_fields(json_str, ['titulo', 'texto_completo'])

            # Sanitiza campos problemáticos com aspas internas não escapadas (ex.: texto_completo, titulo)
            def _escape_inner_quotes_for_field(s: str, field: str) -> str:
                # casa: "field": "...CONTEUDO...",  até a próxima chave conhecida
                proxima_chave = r'("texto_completo"|"jornal"|"autor"|"pagina"|"data"|"categoria"|"tag"|"prioridade"|"relevance_score"|"relevance_reason"|\})'
                pattern = rf'("{field}"\s*:\s*")(.*?)(")\s*,\s*{proxima_chave}'
                def repl(m: re.Match) -> str:
                    inicio = m.group(1)
                    conteudo = m.group(2)
                    fim = m.group(3)
                    resto = m.group(4)
                    # Normaliza quebras de linha para \n e escapa aspas não escapadas
                    conteudo = conteudo.replace('\r\n', '\n').replace('\r', '\n')
                    conteudo = conteudo.replace('\n', '\\n')
                    conteudo = re.sub(r'(?<!\\)"', r'\\"', conteudo)
                    return f"{inicio}{conteudo}{fim}, {resto}"
                return re.sub(pattern, repl, s, flags=re.DOTALL)

            # Já sanitizado por _sanitize_string_fields; evita reintroduzir \n ou quebrar aspas com regex

            # Remove sequências de escape fora de strings (ex.: \\n entre campos)
            def _remove_escapes_outside_strings(s: str) -> str:
                result_chars: List[str] = []
                in_string = False
                escape_next = False
                i = 0
                while i < len(s):
                    ch = s[i]
                    if in_string:
                        if escape_next:
                            result_chars.append(ch)
                            escape_next = False
                        else:
                            if ch == '\\':
                                result_chars.append(ch)
                                escape_next = True
                            elif ch == '"':
                                result_chars.append(ch)
                                in_string = False
                            else:
                                result_chars.append(ch)
                        i += 1
                        continue
                    # Fora de string
                    if ch == '"':
                        result_chars.append(ch)
                        in_string = True
                        i += 1
                        continue
                    # Remove sequências de barras invertidas seguidas de n/r/t (qualquer quantidade de barras)
                    if ch == '\\':
                        j = i
                        # conta barras consecutivas
                        while j < len(s) and s[j] == '\\':
                            j += 1
                        if j < len(s) and s[j] in ('n', 'r', 't'):
                            # descarta todas as barras e o caractere de controle
                            i = j + 1
                            continue
                    # Normaliza: após vírgula, remova espaçamentos e escapes fora de string até o próximo token
                    if ch == ',':
                        result_chars.append(ch)
                        i += 1
                        # pular espaços, quebras e escapes estilo \n fora de string
                        while i < len(s):
                            if s[i] in (' ', '\n', '\r', '\t'):
                                i += 1
                                continue
                            if s[i] == '\\':
                                k = i
                                while k < len(s) and s[k] == '\\':
                                    k += 1
                                if k < len(s) and s[k] in ('n', 'r', 't'):
                                    i = k + 1
                                    continue
                            break
                        continue
                    # mantém demais caracteres
                    result_chars.append(ch)
                    i += 1
                return ''.join(result_chars)

            json_str = _remove_escapes_outside_strings(json_str)

            # Remove comentários estilo // e /* */
            json_str = re.sub(r"//.*?$", "", json_str, flags=re.MULTILINE)
            json_str = re.sub(r"/\*[\s\S]*?\*/", "", json_str)

            # Normaliza aspas tipográficas para ASCII
            json_str = (json_str
                        .replace("\u201c", '"').replace("\u201d", '"')
                        .replace("\u2018", "'").replace("\u2019", "'")
                        .replace("“", '"').replace("”", '"')
                        .replace("‘", "'").replace("’", "'"))

            # Corrige chaves com aspas simples: {'key': ...} -> {"key": ...}
            json_str = re.sub(r"\'(\w+)\':", r'"\1":', json_str)

            # Aspas em chaves não citadas simples: {key: ...} -> {"key": ...}
            json_str = re.sub(r'([\{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', json_str)

            # Converte valores entre aspas simples para aspas duplas em contextos comuns (: 'valor', ['a','b'])
            json_str = re.sub(r'(:\s*)\'([^\'\\]*(?:\\.[^\'\\]*)*)\'', r'\1"\2"', json_str)
            json_str = re.sub(r'(\[\s*)\'([^\'\\]*(?:\\.[^\'\\]*)*)\'', r'\1"\2"', json_str)
            json_str = re.sub(r"\'([^\'\\]*(?:\\.[^\'\\]*)*)\'(\s*[\],])", r'"\1"\2', json_str)

            # Converte booleanos/None estilo Python para JSON
            json_str = re.sub(r"\bTrue\b", "true", json_str)
            json_str = re.sub(r"\bFalse\b", "false", json_str)
            json_str = re.sub(r"\bNone\b", "null", json_str)

            # Remove quebras de linha internas em strings e normaliza espaços
            def _compactar_strings(m: re.Match) -> str:
                txt = m.group(0)
                # preserva aspas externas
                if len(txt) >= 2 and txt[0] == '"' and txt[-1] == '"':
                    inner = txt[1:-1]
                    # normaliza quebras reais e sequências escapadas para espaço
                    inner = inner.replace('\r', ' ').replace('\n', ' ')
                    inner = inner.replace('\\n', ' ').replace('\\r', ' ').replace('\\t', ' ')
                    inner = re.sub(r'\s+', ' ', inner)
                    return '"' + inner + '"'
                return txt
            json_str = re.sub(r'"[^"\\]*(?:\\.[^"\\])*"', _compactar_strings, json_str)

            # Escapa barras invertidas que não fazem parte de sequência JSON válida
            json_str = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_str)

            # Remove vírgulas à direita antes de } ou ]
            json_str = re.sub(r",\s*(\}|\])", r"\1", json_str)
        except Exception as e:
            print(f"  ⚠️ Erro durante correção de string antes do parse: {e}")

        # Helper: imprime contexto do erro com posição (apenas uma vez por resposta)
        printed_error_context = {"done": False}
        def _debug_print_json_error(tag: str, err: json.JSONDecodeError, s: str) -> None:
            try:
                ctx_info = ""
                if contexto:
                    ctx_info = f" [arquivo={contexto.get('arquivo')}, pagina={contexto.get('pagina')}, temp={contexto.get('temp_pdf')}]"
                print(f"  🧩 Detalhe do erro{ctx_info}: {tag} @char {err.pos} (linha {err.lineno}, col {err.colno})")
                if not printed_error_context["done"]:
                    start = max(0, err.pos - 120)
                    end = min(len(s), err.pos + 120)
                    snippet = s[start:end]
                    pointer = ' ' * (err.pos - start) + '^'
                    print("  --- trecho próximo ao erro ---")
                    print(snippet[:500])
                    print(pointer)
                    print("  --- fim do trecho ---")
                    printed_error_context["done"] = True
            except Exception:
                pass

        # Tentativa com JSON sanitizado
        try:
            dados = json.loads(json_str)
            if isinstance(dados, list):
                return dados
            if isinstance(dados, dict):
                return [dados]
            return []
        except json.JSONDecodeError as e:
            print(f"  ❌ Erro ao decodificar JSON após sanitização: {e}")
            _debug_print_json_error("sanitizado", e, json_str)

        # Se ainda falhou, última tentativa com extração mais tolerante
        print("  🔍 Tentando extração alternativa de campos...")
        
        # Busca por padrões mais flexíveis
        # Aceita aspas não escapadas no meio do texto
        alt_pattern = re.compile(
            r'"titulo"\s*:\s*"([^"]*(?:"[^:,}]*)*?)"[^{}]*?"texto_completo"\s*:\s*"([^"]*(?:"[^:,}]*)*?)"',
            re.DOTALL
        )
        
        for match in alt_pattern.finditer(resposta):
            titulo = match.group(1).replace('\n', ' ').strip()
            texto = match.group(2).replace('\n', ' ').strip()
            
            if titulo and texto:
                artigos_extraidos.append({
                    'titulo': titulo,
                    'texto_completo': texto,
                    'jornal': contexto.get('arquivo', '').replace('.pdf', '') if contexto else None,
                    'pagina': contexto.get('pagina') if contexto else None
                })

        if not artigos_extraidos:
            print("  ⚠️ Nenhum JSON válido foi extraído desta resposta.")
        return artigos_extraidos

    def _processar_chunk_pdf_com_ia(self, pdf_path: Path, nome_arquivo_original: str, numero_pagina: int | None = None) -> List[Dict[str, Any]]:
        """
        Método central que envia um arquivo PDF (completo ou um chunk)
        para a API do Gemini e processa a resposta.
        """
        artigos_formatados = []
        try:
            print(f"  🧠 Enviando '{pdf_path.name}' para extração via Gemini File API...")
            # Compatibilidade com diferentes clientes (google.genai vs google.generativeai wrappers)
            uploaded_file = None
            try:
                # API mais recente (google.genai)
                uploaded_file = self.client.files.upload(file=str(pdf_path))
            except TypeError:
                # Fallback: algumas versões aceitam 'path='
                uploaded_file = self.client.files.upload(path=str(pdf_path))

            # Aguarda processamento do arquivo na File API
            while getattr(uploaded_file, "state", None) and getattr(uploaded_file.state, "name", None) == "PROCESSING":
                time.sleep(0.2)
                uploaded_file = self.client.files.get(name=uploaded_file.name)

            if uploaded_file.state.name != "ACTIVE":
                raise Exception(f"Falha no processamento do arquivo na API: {uploaded_file.state.name}")
            
            # Geração de conteúdo: tenta a interface nova .models.generate_content, com fallback seguro
            response = None
            if hasattr(self.client, 'models') and hasattr(self.client.models, 'generate_content'):
                response = self.client.models.generate_content(
                    model='gemini-3.1-flash-lite-preview',
                    contents=[uploaded_file, self.extraction_prompt],
                    config=self.generation_config_decision
                )
            elif hasattr(self.client, 'generate_content'):
                response = self.client.generate_content(
                    model='models/gemini-3.1-flash-lite-preview',
                    contents=[uploaded_file, self.extraction_prompt],
                    generation_config=self.generation_config_decision
                )
            else:
                raise AttributeError("Cliente Gemini não possui método generate_content compatível")
            self.client.files.delete(name=uploaded_file.name)  # Limpeza

            # Tratamento de resposta
            def _get_response_text(resp: Any) -> Optional[str]:
                # 1) Atributo direto
                try:
                    t = getattr(resp, 'text', None)
                    if isinstance(t, str) and t.strip():
                        return t
                except Exception:
                    pass
                # 2) Novo SDK: candidates -> content.parts[].text
                try:
                    candidates = getattr(resp, 'candidates', None)
                    if candidates:
                        parts_text: List[str] = []
                        for cand in candidates:
                            content = getattr(cand, 'content', None) or {}
                            parts = getattr(content, 'parts', None) or []
                            for p in parts:
                                text_val = getattr(p, 'text', None)
                                if isinstance(text_val, str):
                                    parts_text.append(text_val)
                        if parts_text:
                            return "\n".join(parts_text)
                except Exception:
                    pass
                # 3) Algumas libs expõem output_text
                try:
                    ot = getattr(resp, 'output_text', None)
                    if isinstance(ot, str) and ot.strip():
                        return ot
                except Exception:
                    pass
                # 4) Fallback via dict
                try:
                    to_dict = getattr(resp, 'to_dict', None)
                    d = to_dict() if callable(to_dict) else None
                    if d and isinstance(d, dict):
                        cands = d.get('candidates') or []
                        parts_text: List[str] = []
                        for cand in cands:
                            content = (cand or {}).get('content') or {}
                            parts = content.get('parts') or []
                            for p in parts:
                                tv = (p or {}).get('text')
                                if isinstance(tv, str):
                                    parts_text.append(tv)
                        if parts_text:
                            return "\n".join(parts_text)
                except Exception:
                    pass
                return None

            response_text = _get_response_text(response)
            if not response_text:
                print("  ⚠️ API não retornou conteúdo utilizável para este trecho/página.")
                return artigos_formatados

            noticias_extraidas = self._extrair_json_da_resposta(
                response_text,
                {"arquivo": nome_arquivo_original, "pagina": numero_pagina, "temp_pdf": pdf_path.name}
            )
            print(f"  ✨ {len(noticias_extraidas)} notícias candidatas extraídas.")
            if not noticias_extraidas:
                # Amostra limitada da resposta para debugging (apenas em caso de falha)
                preview = response_text[:400].replace('\n', ' ') if isinstance(response_text, str) else ''
                print(f"  🛠️ Amostra da resposta (truncada): {preview}")

            # Converte a saída do LLM para o formato esperado pelo banco de dados
            for noticia in noticias_extraidas:
                if isinstance(noticia, dict) and noticia.get('texto_completo'):
                    # Determina jornal (prioriza extraído pela IA; fallback: nome do arquivo)
                    jornal_extraido = noticia.get('jornal') or nome_arquivo_original.replace('.pdf', '')
                    # Determina página (prioriza extraído; fallback: número da página processada)
                    pagina_extraida = noticia.get('pagina') if noticia.get('pagina') not in [None, '', 'N/A'] else numero_pagina
                    # Determina URL quando disponível
                    url_detectada = noticia.get('url') or noticia.get('link')
                    # Gera título robusto quando ausente/genérico
                    titulo_extraido = (noticia.get('titulo') or '').strip()
                    if titulo_e_generico(titulo_extraido):
                        titulo_extraido = gerar_titulo_fallback_curto(noticia.get('texto_completo'))
                    # Decide tipo_fonte por texto (OCR sempre físico, exceto se idioma não for PT → internacional)
                    tipo_por_texto = self.inferir_tipo_por_texto(noticia.get('texto_completo'), tipo_arquivo='pdf', tem_url=False)

                    artigos_formatados.append({
                        'texto_bruto': noticia['texto_completo'],
                        'url_original': url_detectada,
                        'metadados': {
                            'titulo': titulo_extraido or gerar_titulo_fallback_curto(noticia.get('texto_completo')),
                            'subtitulo': '',
                            # Fonte original deve refletir o jornal para alinhar com o fluxo dos JSONs
                            'fonte_original': jornal_extraido,
                            'arquivo_origem': nome_arquivo_original,
                            'data_processamento': get_datetime_brasil_str(),
                            'tipo_arquivo': 'pdf',
                            'tipo_fonte_detectado': tipo_por_texto,
                            # Campos extraídos pela IA
                            'jornal': jornal_extraido,
                            'autor': noticia.get('autor') or 'N/A',
                            'pagina': pagina_extraida,
                            'data_publicacao': noticia.get('data') or None,
                            'data_ultima_modificacao': None,
                            'categoria': noticia.get('categoria') or None,
                            'tags_originais': [],
                            'id_hash_original': '',
                            # Alinhamento de compatibilidade com JSONs
                            'link': url_detectada,
                            # Mantém campos de IA apenas como metadados informativos
                            'tag_ia': noticia.get('tag'),
                            'prioridade_ia': noticia.get('prioridade'),
                            'relevance_score_ia': noticia.get('relevance_score'),
                            'relevance_reason_ia': noticia.get('relevance_reason')
                        }
                    })

            # Fallback: se nada válido foi extraído, usa texto simples da página
            if not artigos_formatados and PDF_AVAILABLE:
                try:
                    with fitz.open(pdf_path) as temp_doc:
                        texto_pagina = ''
                        if temp_doc.page_count > 0:
                            texto_pagina = (temp_doc.load_page(0).get_text() or '').strip()
                    if texto_pagina:
                        primeira_linha = texto_pagina.split('\n', 1)[0].strip()
                        if titulo_e_generico(primeira_linha):
                            primeira_linha = gerar_titulo_fallback_curto(texto_pagina)
                        jornal_fallback = nome_arquivo_original.replace('.pdf', '')
                        artigos_formatados.append({
                            'texto_bruto': texto_pagina,
                            'url_original': None,
                            'metadados': {
                                'titulo': (primeira_linha or gerar_titulo_fallback_curto(texto_pagina)) or f"{jornal_fallback} - Página {numero_pagina or ''}",
                                'subtitulo': '',
                                'fonte_original': jornal_fallback,
                                'arquivo_origem': nome_arquivo_original,
                                'data_processamento': get_datetime_brasil_str(),
                                'tipo_arquivo': 'pdf',
                                'jornal': jornal_fallback,
                                'pagina': numero_pagina,
                                'data_publicacao': None,
                                'data_ultima_modificacao': None,
                                'categoria': None,
                                'tags_originais': [],
                                'id_hash_original': '',
                                'link': None
                            }
                        })
                        print("  🔁 Fallback: extração simples de texto aplicada para esta página.")
                except Exception as fe:
                    print(f"  ⚠️ Fallback de texto falhou: {fe}")
        except Exception as e:
            print(f"  ❌ Erro durante a chamada à API Gemini para '{pdf_path.name}': {e}")
        
        return artigos_formatados

    def processar_pdf(self, file_path: Path) -> List[Dict[str, Any]]:
        """
        Orquestra a extração de notícias de um arquivo PDF.
        - Se o cliente Gemini não estiver disponível, faz uma extração de texto simples.
        - Se estiver disponível, usa a File API, com chunking para arquivos grandes.
        """
        if not PDF_AVAILABLE: 
            return []

        if not self.client:
            print(f"  ⚠️ Extração de texto simples (sem IA) para '{file_path.name}'...")
            artigos_simples: List[Dict[str, Any]] = []
            with fitz.open(file_path) as doc:
                num_paginas = len(doc)
                jornal_fallback = file_path.stem
                for idx, page in enumerate(doc, start=1):
                    texto_pagina = (page.get_text() or '').strip()
                    if not texto_pagina:
                        continue
                    # Título como primeira linha da página
                    primeira_linha = texto_pagina.split('\n', 1)[0].strip()
                    tipo_por_texto = self.inferir_tipo_por_texto(texto_pagina, tipo_arquivo='pdf', tem_url=False)
                    artigos_simples.append({
                        'texto_bruto': texto_pagina,
                        'url_original': None,
                        'metadados': {
                            'titulo': primeira_linha or f"{jornal_fallback} - Página {idx}",
                            'fonte_original': jornal_fallback,
                            'arquivo_origem': file_path.name,
                            'data_processamento': get_datetime_brasil_str(),
                            'tipo_arquivo': 'pdf',
                            'tipo_fonte_detectado': tipo_por_texto,
                            'jornal': jornal_fallback,
                            'pagina': idx,
                            'total_paginas_pdf': num_paginas
                        }
                    })
            if not artigos_simples:
                return []
            return artigos_simples

        # Fluxo principal com IA: página a página EM PARALELO para performance
        print(f"🚀 Iniciando extração com IA (página a página) para: {file_path.name}")
        artigos_finais: List[Dict[str, Any]] = []
        try:
            with fitz.open(file_path) as doc:
                num_paginas = len(doc)
                print(f"  📄 Total de páginas: {num_paginas}")

                # Pre-filtro: padroes de paginas que NAO sao noticias (balancos, DRE, etc)
                # Detectados via texto extraido por PyMuPDF ANTES de enviar ao Gemini
                _SKIP_PATTERNS = [
                    'demonstrações financeiras', 'demonstracoes financeiras',
                    'notas explicativas às demonstrações', 'notas explicativas as demonstracoes',
                    'balanço patrimonial', 'balanco patrimonial',
                    'demonstração do resultado', 'demonstracao do resultado',
                    'demonstração de fluxo de caixa', 'demonstracao de fluxo de caixa',
                    'demonstração das mutações do patrimônio', 'demonstracao das mutacoes',
                    'relatório dos auditores independentes', 'relatorio dos auditores',
                    'valores expressos em milhares de reais',
                    'controladora consolidado',
                ]

                def _is_financial_page(page_text: str) -> bool:
                    """Detecta se a pagina e demonstracao financeira/balanco (nao e noticia)."""
                    text_lower = page_text.lower()[:2000]  # So precisa dos primeiros 2000 chars
                    matches = sum(1 for p in _SKIP_PATTERNS if p in text_lower)
                    # Se tem 2+ padroes de balanco, quase certamente nao e noticia
                    if matches >= 2:
                        return True
                    # Se tem muito numero em relacao a texto, provavelmente e tabela
                    digits = sum(1 for c in page_text[:3000] if c.isdigit())
                    letters = sum(1 for c in page_text[:3000] if c.isalpha())
                    if letters > 0 and digits / letters > 0.4:
                        return True
                    return False

                def processar_pagina(idx: int) -> List[Dict[str, Any]]:
                    numero_pagina_local = idx + 1
                    print(f"  🔎 Processando página {numero_pagina_local}/{num_paginas}...")
                    
                    # Pre-filtro: extrai texto via PyMuPDF e verifica se e balanco/DRE
                    try:
                        page = doc[idx]
                        page_text = page.get_text("text") or ""
                        if _is_financial_page(page_text):
                            print(f"  ⏭️ Página {numero_pagina_local} ignorada (demonstração financeira/balanço)")
                            return []
                    except Exception:
                        pass  # Se falhar, envia para Gemini normalmente
                    
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_file:
                        temp_page_path = Path(temp_file.name)
                    try:
                        with fitz.open() as page_doc:
                            page_doc.insert_pdf(doc, from_page=idx, to_page=idx)
                            page_doc.save(str(temp_page_path))
                        return self._processar_chunk_pdf_com_ia(
                            temp_page_path, file_path.name, numero_pagina=numero_pagina_local
                        )
                    except Exception as e:
                        print(f"  ❌ Erro ao processar página {numero_pagina_local}: {e}")
                        return []
                    finally:
                        if temp_page_path.exists():
                            try:
                                os.remove(temp_page_path)
                            except Exception:
                                pass

                # Executa páginas em paralelo com limite para não saturar a API
                max_workers = min(8, num_paginas)  # limite conservador
                try:
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                        resultados = list(executor.map(processar_pagina, range(num_paginas)))
                    for lista in resultados:
                        if lista:
                            artigos_finais.extend(lista)
                except Exception as e:
                    # Fallback sequencial em caso de ambientes sem suporte a threads
                    print(f"  ⚠️ Falha no paralelismo, executando sequencialmente: {e}")
                    for idx in range(num_paginas):
                        artigos_finais.extend(processar_pagina(idx))
        except Exception as e:
            print(f"❌ Erro crítico ao orquestrar processamento do PDF '{file_path.name}': {e}")

        return artigos_finais

    def _criar_noticia_basica(self, texto_completo: str, file_path: Path) -> Dict[str, Any]:
        """
        Cria uma notícia básica quando não há LLM disponível.
        """
        # Extrai primeira linha como título
        linhas = texto_completo.split('\n')
        titulo = linhas[0].strip() if linhas else "Sem título"
        
        return {
            'texto_bruto': texto_completo.strip(),
            'url_original': None,
            'metadados': {
                'titulo': titulo,
                'fonte_original': 'PDF',
                'categoria': 'Geral',
                'data_publicacao': get_date_brasil_str(),
                'data_ultima_modificacao': get_date_brasil_str(),
                'tags_originais': [],
                'id_hash_original': '',
                'arquivo_origem': file_path.name,
                'data_processamento': get_datetime_brasil_str(),
                'tipo_arquivo': 'pdf'
            }
        }

    # --- MÉTODOS EXISTENTES (AJUSTADOS) ---

    def processar_json_dump(self, file_path: Path) -> List[Dict[str, Any]]:
        """Processa arquivo JSON no formato dump_crawlers."""
        try:
            print(f"📄 Processando JSON: {file_path.name}")
            
            with open(file_path, 'r', encoding='utf-8') as f:
                dados = json.load(f)
            
            print(f"  📊 Total de itens no JSON: {len(dados)}")
            
            artigos = []
            for i, item in enumerate(dados, 1):
                print(f"  🔍 Processando item {i}/{len(dados)}...")
                
                texto_bruto = item.get('texto_completo', item.get('titulo', ''))
                if texto_bruto:
                    # NOVO: Detecta tipo_fonte usando a nova classificação de três tipos
                    url_original = item.get('link', '')
                    fonte_original = item.get('fonte', 'JSON_Dump')
                    tem_url = bool(url_original.strip())  # Se tem URL, é online
                    
                    # Detecta o tipo usando a nova função
                    # Primeiro: heurística leve por texto para detectar idioma (internacional x pt)
                    tipo_por_texto = self.inferir_tipo_por_texto(texto_bruto, tipo_arquivo='json', tem_url=tem_url)
                    # Segundo: heurística por fonte/domínio
                    tipo_por_fonte = self.detectar_tipo_fonte_completo(
                        fonte_original,
                        tem_url=tem_url,
                        tipo_arquivo='json'
                    )
                    # Combinação: internacional vence se qualquer heurística apontar; senão prefere online
                    tipo_fonte = 'internacional' if (tipo_por_texto == 'internacional' or tipo_por_fonte == 'internacional') else 'brasil_online'
                    
                    artigos.append({
                        'texto_bruto': texto_bruto,
                        'url_original': url_original,
                        'metadados': {
                            'titulo': item.get('titulo', ''),
                            'subtitulo': item.get('subtitulo', ''),
                            'fonte_original': fonte_original,
                            'categoria': item.get('categoria', ''),
                            'data_publicacao': item.get('data_publicacao', ''),
                            'data_ultima_modificacao': item.get('data_ultima_modificacao', ''),
                            'tags_originais': item.get('tags', []),
                            'id_hash_original': item.get('id_hash', ''),
                            'arquivo_origem': file_path.name,
                            'data_processamento': get_datetime_brasil_str(),
                            'tipo_arquivo': 'json',
                            'tipo_fonte_detectado': tipo_fonte,  # NOVO: Armazena o tipo detectado
                            'tem_url': tem_url,  # NOVO: Flag de URL
                            **item  # Adiciona todos os outros campos do JSON original aos metadados
                        }
                    })
                    print(f"    ✅ Item {i} processado: {item.get('titulo', '')[:50]}...")
                else:
                    print(f"    ⚠️ Item {i} sem texto: {item.get('titulo', '')[:50]}...")
            
            print(f"📊 Total de artigos extraídos: {len(artigos)}")
            return artigos
            
        except Exception as e:
            print(f"❌ ERRO ao processar JSON {file_path}: {e}")
            import traceback
            traceback.print_exc()
            return []
            
    def processar_arquivo(self, file_path: Path, usar_api: bool) -> int:
        """Processa um único arquivo (PDF ou JSON) e salva os artigos resultantes."""
        print(f"\n📄 Processando arquivo: {file_path.name}")
        
        artigos_brutos = []
        if file_path.suffix.lower() == '.json':
            print(f"📄 Arquivo JSON detectado")
            artigos_brutos = self.processar_json_dump(file_path)
        elif file_path.suffix.lower() == '.pdf':
            print(f"📰 Arquivo PDF detectado")
            artigos_brutos = self.processar_pdf(file_path)
        else:
            print(f"⚠️ Formato de arquivo não suportado: {file_path.name}")
            return 0
        
        if not artigos_brutos:
            print(f"⚠️ AVISO: Nenhum artigo extraído de {file_path.name}")
            return 0
        
        print(f"📊 Encontrados {len(artigos_brutos)} artigos em {file_path.name}")
        
        # Envia artigos
        sucessos = 0
        dedup_count = 0
        for i, artigo in enumerate(artigos_brutos, 1):
            print(f"  📤 Enviando artigo {i}/{len(artigos_brutos)}...")
            
            if usar_api:
                resultado = self.enviar_artigo_via_api(artigo)
                if resultado:
                    sucessos += 1
                    print(f"    ✅ Artigo {i} enviado via API")
                else:
                    print(f"    ❌ Falha ao enviar artigo {i} via API")
            else:
                resultado = self.enviar_artigo_direto_db(artigo)
                if resultado in ("dedup", "hash_dup"):
                    dedup_count += 1
                    # Nao imprime "salvo" - o print de dedup ja foi feito dentro da funcao
                elif resultado:
                    sucessos += 1
                    print(f"    ✅ Artigo {i} salvo no banco")
                else:
                    print(f"    ❌ Falha ao salvar artigo {i} no banco")
            
            # Aguarda um pouco entre envios
            time.sleep(0.05)
        
        dedup_msg = f" ({dedup_count} duplicatas ignoradas)" if dedup_count else ""
        print(f"🎉 SUCESSO: {sucessos}/{len(artigos_brutos)} artigos processados de {file_path.name}{dedup_msg}")
        return sucessos
        
    def processar_diretorio(self, usar_api: bool) -> Dict[str, int]:
        """Processa um diretório completo em paralelo para otimizar o tempo."""
        print(f"🚀 Iniciando processamento do diretório: {self.files_directory}")
        
        files = list(self.files_directory.glob('*.json')) + list(self.files_directory.glob('*.pdf'))
        
        if not files:
            print("⚠️ Nenhum arquivo .json ou .pdf encontrado para processar.")
            return {"arquivos_processados": 0, "artigos_criados": 0}
            
        print(f"📊 Encontrados {len([f for f in files if f.suffix.lower() == '.json'])} JSONs e {len([f for f in files if f.suffix.lower() == '.pdf'])} PDFs")
        
        # Para processamento sequencial (mais seguro para APIs com rate limits)
        stats = {"arquivos_processados": 0, "artigos_criados": 0}
        
        for i, file_path in enumerate(files, 1):
            print(f"\n📄 [{i}/{len(files)}] Processando: {file_path.name}")
            try:
                num_artigos = self.processar_arquivo(file_path, usar_api)
                stats["artigos_criados"] += num_artigos
                if num_artigos > 0:
                    stats["arquivos_processados"] += 1
                    print(f"✅ Concluído '{file_path.name}': {num_artigos} artigos carregados.")
                else:
                    print(f"⚠️ Nenhum artigo extraído de '{file_path.name}'")
            except Exception as exc:
                print(f"❌ Erro ao processar o arquivo {file_path.name}: {exc}")

        print(f"\n🎉 SUCESSO: Processamento finalizado:")
        print(f"   📁 Arquivos processados: {stats['arquivos_processados']}")
        print(f"   📰 Artigos criados: {stats['artigos_criados']}")
        
        return stats

    # --- MÉTODOS DE ENVIO (MANTIDOS) ---

    def enviar_artigo_via_api(self, artigo_data: Dict[str, Any]) -> bool:
        """
        Envia artigo para a API via HTTP.
        """
        try:
            # Gera hash único
            hash_unico = self.gerar_hash_artigo(
                artigo_data['texto_bruto'], 
                artigo_data.get('url_original', '')
            )
            
            # Prepara dados
            dados_artigo = {
                "hash_unico": hash_unico,
                "texto_bruto": artigo_data['texto_bruto'],
                "url_original": artigo_data.get('url_original'),
                "fonte_coleta": "file_loader",
                "metadados": artigo_data.get('metadados', {})
            }
            
            # Envia para API
            response = self.session.post(
                f"{self.api_base_url}/internal/novo-artigo",
                json=dados_artigo,
                timeout=30
            )
            
            if response.status_code == 200:
                resultado = response.json()
                print(f"SUCESSO: Artigo enviado via API: {resultado['message']}")
                return True
            else:
                print(f"ERRO: Erro ao enviar artigo via API: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"ERRO: Erro de conexão com API: {e}")
            return False

    def enviar_artigo_direto_db(self, artigo_data: Dict[str, Any]) -> bool:
        """
        Envia artigo diretamente para o banco de dados.
        """
        try:
            db = SessionLocal()
            
            # Gera hash único
            hash_unico = self.gerar_hash_artigo(
                artigo_data['texto_bruto'], 
                artigo_data.get('url_original', '')
            )
            
            # Verifica se já existe (dedup exata por hash)
            artigo_existente = get_artigo_by_hash(db, hash_unico)
            if artigo_existente:
                print(f"⚠️ AVISO: Artigo já existe no banco (hash): {artigo_existente.id}")
                return "hash_dup"  # Retorna string para diferenciar de "salvo com sucesso"
            
            # Verifica dedup semantica (artigos muito parecidos nas ultimas 48h)
            try:
                from backend.processing import verificar_duplicata_semantica
                dup = verificar_duplicata_semantica(db, artigo_data['texto_bruto'], threshold=0.85, horas=48)
                if dup:
                    print(f"⚠️ DEDUP SEMANTICA: Artigo similar encontrado (id={dup['artigo_id']}, "
                          f"sim={dup['similaridade']:.2f}, titulo='{dup['titulo']}'). Ignorando.")
                    db.close()
                    return "dedup"  # Retorna string para diferenciar de "salvo com sucesso"
            except Exception as e:
                # Falha na dedup semantica nao impede a insercao
                print(f"[Dedup Semantica] Aviso: {e}")
            
            # Detecta tipo de fonte usando a nova classificação de três tipos
            jornal = artigo_data.get('metadados', {}).get('jornal') or artigo_data.get('metadados', {}).get('fonte_original', '')
            # Para PDFs, usa a nova classificação completa
            tipo_fonte = self.detectar_tipo_fonte_completo(jornal, tem_url=False, tipo_arquivo='pdf')
            
            # Fallback para compatibilidade com sistema antigo (nacional/internacional)
            if tipo_fonte not in ('brasil_fisico', 'brasil_online', 'internacional'):
                tipo_fonte_antigo = inferir_tipo_fonte_por_jornal(jornal)
                if tipo_fonte_antigo == 'internacional':
                    tipo_fonte = 'internacional'
                else:
                    tipo_fonte = 'brasil_fisico'  # PDFs brasileiros = físico
            
            # Cria novo artigo
            dados_artigo = ArtigoBrutoCreate(
                hash_unico=hash_unico,
                texto_bruto=artigo_data['texto_bruto'],
                url_original=artigo_data.get('url_original'),
                fonte_coleta="file_loader",
                metadados=artigo_data.get('metadados', {})
            )
            
            novo_artigo = create_artigo_bruto(db, dados_artigo)
            
            # Salva dados originais nos novos campos
            metadados = artigo_data.get('metadados', {})
            
            # NOVO: Se existir tipo_fonte_detectado nos metadados (pdf ou json), usa-o
            if metadados.get('tipo_fonte_detectado') in ('brasil_fisico', 'brasil_online', 'internacional'):
                tipo_fonte = metadados['tipo_fonte_detectado']
            
            # Atualiza campos originais (com verificação de existência)
            try:
                if hasattr(novo_artigo, 'subtitulo'):
                    novo_artigo.subtitulo = metadados.get('subtitulo')
                if hasattr(novo_artigo, 'fonte_original'):
                    novo_artigo.fonte_original = metadados.get('fonte_original')
                if hasattr(novo_artigo, 'tags_originais'):
                    novo_artigo.tags_originais = metadados.get('tags_originais')
                if hasattr(novo_artigo, 'id_hash_original'):
                    novo_artigo.id_hash_original = metadados.get('id_hash_original')
                # Se 'jornal' processado vier vazio, preenche com 'fonte_original'
                if hasattr(novo_artigo, 'jornal') and not novo_artigo.jornal:
                    novo_artigo.jornal = metadados.get('jornal') or metadados.get('fonte_original')
                
                # Converte datas se presentes
                if metadados.get('data_publicacao'):
                    try:
                        from datetime import datetime
                        novo_artigo.data_publicacao = datetime.fromisoformat(metadados['data_publicacao'].replace('Z', '+00:00'))
                    except:
                        pass
                
                if metadados.get('data_ultima_modificacao'):
                    try:
                        if hasattr(novo_artigo, 'data_ultima_modificacao'):
                            novo_artigo.data_ultima_modificacao = datetime.fromisoformat(metadados['data_ultima_modificacao'].replace('Z', '+00:00'))
                    except:
                        pass
                
                # Salva categoria original
                if hasattr(novo_artigo, 'categoria'):
                    novo_artigo.categoria = metadados.get('categoria')
                
                # Salva tipo de fonte
                if hasattr(novo_artigo, 'tipo_fonte'):
                    novo_artigo.tipo_fonte = tipo_fonte
                    
            except Exception as e:
                print(f"⚠️ AVISO: Alguns campos novos não estão disponíveis: {e}")
            
            db.commit()
            db.refresh(novo_artigo)
            
            create_log(db, "INFO", "file_loader", 
                      f"Artigo criado: {novo_artigo.id}",
                      {"arquivo": artigo_data.get('metadados', {}).get('arquivo_origem', 'desconhecido')})
            
            print(f"✅ SUCESSO: Artigo criado no banco: {novo_artigo.id}")
            return True
            
        except Exception as e:
            print(f"❌ ERRO: Erro ao criar artigo no banco: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            if 'db' in locals():
                db.close()

    def verificar_api_status(self) -> bool:
        """Verifica se a API está funcionando."""
        try:
            print(f"🔍 Verificando status da API: {self.api_base_url}")
            response = self.session.get(f"{self.api_base_url}/health", timeout=10)
            if response.status_code == 200:
                status = response.json()
                print(f"✅ SUCESSO: API Status: {status['status']}")
                return True
            else:
                print(f"❌ ERRO: API não está saudável: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ ERRO: Erro ao verificar API: {e}")
            return False


def main():
    """Função principal para carregamento de arquivos."""
    print("=" * 60)
    print("BTG AlphaFeed - Carregador de Arquivos")
    print("=" * 60)
    
    # Configurações
    files_dir = input("Diretório dos arquivos (../pdfs): ").strip()
    if not files_dir:
        files_dir = "../pdfs"
    
    # Cria instância do carregador
    try:
        loader = FileLoader(files_directory=files_dir)
    except FileNotFoundError as e:
        print(f"ERRO: {e}")
        return
    
    # Pergunta sobre método de envio
    print("\nMétodo de envio:")
    print("1. Via API HTTP (recomendado)")
    print("2. Direto no banco de dados")
    
    metodo = input("Escolha o método (1/2): ").strip()
    usar_api = metodo != "2"
    
    if usar_api:
        # Verifica status da API
        if not loader.verificar_api_status():
            print("\nERRO: API não está disponível. Verifique se o backend está rodando.")
            return
    
    # Pergunta se deve executar
    executar = input("\nExecutar carregamento? (s/N): ").lower().strip()
    if executar in ['s', 'sim', 'yes', 'y']:
        stats = loader.processar_diretorio(usar_api=usar_api)
        print(f"\nResumo: {stats['artigos_criados']} artigos criados de {stats['arquivos_processados']} arquivos")
    else:
        print("Carregamento cancelado pelo usuário.")
    
    print("\n" + "=" * 60)
    print("Dicas:")
    print("   - Coloque arquivos JSON e PDF na pasta especificada")
    print("   - JSONs devem seguir o formato dump_crawlers")
    print("   - PDFs serão extraídos usando IA (se cliente Gemini disponível)")
    print("   - Artigos duplicados são automaticamente ignorados")
    print("=" * 60)


if __name__ == "__main__":
    main() 