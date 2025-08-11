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
    from ..prompts import PROMPT_EXTRACAO_PERMISSIVO_V8
    from ..utils import get_datetime_brasil_str, get_date_brasil_str
except ImportError:
    # Fallback para execução direta
    try:
        from database import SessionLocal
        from models import ArtigoBrutoCreate
        from crud import create_artigo_bruto, get_artigo_by_hash, create_log
        from prompts import PROMPT_EXTRACAO_PERMISSIVO_V8
        from utils import get_datetime_brasil_str, get_date_brasil_str
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
        self.extraction_prompt = PROMPT_EXTRACAO_PERMISSIVO_V8
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

    # --- LÓGICA DE PROCESSAMENTO DE PDF (REFATORADA) ---

    def _extrair_json_da_resposta(self, resposta: str) -> List[Dict[str, Any]]:
        """
        Extrai JSON de forma robusta (compatível com a usada no poc_silva):
        - Prioriza bloco ```json
        - Fallback para primeiro '[' ou '{'
        - Retorna lista vazia em caso de falha, com logs mínimos
        """
        if not isinstance(resposta, str) or not resposta.strip():
            print("  ❌ Resposta da API vazia.")
            return []
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', resposta, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
        else:
            # Busca melhor marcador de início
            pos_col = resposta.find('[')
            pos_obj = resposta.find('{')
            start = -1
            if pos_col != -1 and (pos_obj == -1 or pos_col < pos_obj):
                start = pos_col
            elif pos_obj != -1:
                start = pos_obj
            if start == -1:
                print("  ❌ Nenhum marcador JSON encontrado na resposta.")
                return []
            json_str = resposta[start:].strip()
        try:
            dados = json.loads(json_str)
            return dados if isinstance(dados, list) else [dados] if isinstance(dados, dict) else []
        except json.JSONDecodeError as e:
            print(f"  ❌ Erro ao decodificar JSON: {e}")
            return []

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
                time.sleep(1)
                uploaded_file = self.client.files.get(name=uploaded_file.name)

            if uploaded_file.state.name != "ACTIVE":
                raise Exception(f"Falha no processamento do arquivo na API: {uploaded_file.state.name}")
            
            # Geração de conteúdo: prioriza a interface nova .models.generate_content
            response = None
            try:
                response = self.client.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=[uploaded_file, self.extraction_prompt],
                    config=self.generation_config_decision
                )
            except Exception:
                # Fallback para clientes que expõem .generate_content na raiz
                response = self.client.generate_content(
                    model='models/gemini-2.0-flash',
                    contents=[uploaded_file, self.extraction_prompt],
                    generation_config=self.generation_config_decision
                )
            self.client.files.delete(name=uploaded_file.name)  # Limpeza

            # Tratamento de resposta
            response_text = None
            try:
                response_text = response.text
            except Exception:
                # Alguns clientes podem levantar erro se conteúdo for bloqueado
                response_text = None
            if not response_text:
                print("  ⚠️ API não retornou conteúdo utilizável para este trecho/página.")
                return artigos_formatados

            noticias_extraidas = self._extrair_json_da_resposta(response_text)
            print(f"  ✨ {len(noticias_extraidas)} notícias candidatas extraídas.")

            # Converte a saída do LLM para o formato esperado pelo banco de dados
            for noticia in noticias_extraidas:
                if isinstance(noticia, dict) and noticia.get('titulo') and noticia.get('texto_completo'):
                    # Determina jornal (prioriza extraído pela IA; fallback: nome do arquivo)
                    jornal_extraido = noticia.get('jornal') or nome_arquivo_original.replace('.pdf', '')
                    # Determina página (prioriza extraído; fallback: número da página processada)
                    pagina_extraida = noticia.get('pagina') if noticia.get('pagina') not in [None, '', 'N/A'] else numero_pagina
                    # Determina URL quando disponível
                    url_detectada = noticia.get('url') or noticia.get('link')
                    artigos_formatados.append({
                        'texto_bruto': noticia['texto_completo'],
                        'url_original': url_detectada,
                        'metadados': {
                            'titulo': noticia.get('titulo') or '',
                            'subtitulo': '',
                            # Fonte original deve refletir o jornal para alinhar com o fluxo dos JSONs
                            'fonte_original': jornal_extraido,
                            'arquivo_origem': nome_arquivo_original,
                            'data_processamento': get_datetime_brasil_str(),
                            'tipo_arquivo': 'pdf',
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
                    artigos_simples.append({
                        'texto_bruto': texto_pagina,
                        'url_original': None,
                        'metadados': {
                            'titulo': primeira_linha or f"{jornal_fallback} - Página {idx}",
                            'fonte_original': jornal_fallback,
                            'arquivo_origem': file_path.name,
                            'data_processamento': get_datetime_brasil_str(),
                            'tipo_arquivo': 'pdf',
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

                def processar_pagina(idx: int) -> List[Dict[str, Any]]:
                    numero_pagina_local = idx + 1
                    print(f"  🔎 Processando página {numero_pagina_local}/{num_paginas}...")
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
                    artigos.append({
                        'texto_bruto': texto_bruto,
                        'url_original': item.get('link', ''),
                        'metadados': {
                            'titulo': item.get('titulo', ''),
                            'subtitulo': item.get('subtitulo', ''),
                            'fonte_original': item.get('fonte', 'JSON_Dump'),
                            'categoria': item.get('categoria', ''),
                            'data_publicacao': item.get('data_publicacao', ''),
                            'data_ultima_modificacao': item.get('data_ultima_modificacao', ''),
                            'tags_originais': item.get('tags', []),
                            'id_hash_original': item.get('id_hash', ''),
                            'arquivo_origem': file_path.name,
                            'data_processamento': get_datetime_brasil_str(),
                            'tipo_arquivo': 'json',
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
        for i, artigo in enumerate(artigos_brutos, 1):
            print(f"  📤 Enviando artigo {i}/{len(artigos_brutos)}...")
            
            if usar_api:
                if self.enviar_artigo_via_api(artigo):
                    sucessos += 1
                    print(f"    ✅ Artigo {i} enviado via API")
                else:
                    print(f"    ❌ Falha ao enviar artigo {i} via API")
            else:
                if self.enviar_artigo_direto_db(artigo):
                    sucessos += 1
                    print(f"    ✅ Artigo {i} salvo no banco")
                else:
                    print(f"    ❌ Falha ao salvar artigo {i} no banco")
            
            # Aguarda um pouco entre envios
            time.sleep(0.2)
        
        print(f"🎉 SUCESSO: {sucessos}/{len(artigos_brutos)} artigos processados de {file_path.name}")
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
            
            # Verifica se já existe
            artigo_existente = get_artigo_by_hash(db, hash_unico)
            if artigo_existente:
                print(f"⚠️ AVISO: Artigo já existe no banco: {artigo_existente.id}")
                return True
            
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