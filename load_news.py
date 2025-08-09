#!/usr/bin/env python3
"""
Script de comando para carregar notícias no BTG AlphaFeed.
Esta versão foi refatorada para usar uma classe FileLoader robusta, que lida
com a extração de notícias de PDFs via Gemini API e processamento paralelo.
"""

import sys
import argparse
import os
from pathlib import Path

# Adiciona o diretório backend ao path para importações corretas
backend_dir = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend_dir))

# Importa a classe que agora contém toda a lógica de processamento
from collectors.file_loader import FileLoader

# A verificação de dependências é importante para guiar o usuário
try:
    from dotenv import load_dotenv
    # Preferir o novo SDK (google-genai) como no poc_silva.py
    try:
        from google import genai as genai_new
        from google.genai import types as genai_types
        NEW_GENAI_AVAILABLE = True
    except Exception:
        NEW_GENAI_AVAILABLE = False
        genai_new = None
        genai_types = None

    import google.generativeai as genai_old  # ainda usado pelo process_articles
    import fitz  # PyMuPDF
    GEMINI_AVAILABLE = True
    print("✅ Módulos para processamento de PDF (Gemini, PyMuPDF) estão disponíveis.")
except ImportError:
    GEMINI_AVAILABLE = False
    NEW_GENAI_AVAILABLE = False
    genai_new = None
    genai_types = None
    print("❌ AVISO: Dependências de Gemini/PyMuPDF ausentes.")
    print("   Instale com: pip install google-genai google-generativeai pymupdf python-dotenv")


def main():
    """Função principal do script de comando."""
    parser = argparse.ArgumentParser(
        description="Carregador de notícias brutas para BTG AlphaFeed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos de uso:
  python load_news.py                                 # Processa o diretório padrão ../pdfs
  python load_news.py --dir /caminho/para/noticias    # Especifica um diretório
  python load_news.py --file ../pdfs/arquivo.pdf      # Processa um único arquivo (PDF ou JSON)
  python load_news.py --direct                        # Salva direto no banco (sem usar a API local)
  python load_news.py -y                              # Executa sem pedir confirmação

NOTA: Este script agora extrai notícias de PDFs (se a API Gemini estiver configurada)
e as carrega como artigos brutos.
        """
    )
    
    parser.add_argument("--dir", "--directory", type=str, default="../pdfs", 
                       help="Diretório com arquivos para processar (padrão: ../pdfs)")
    parser.add_argument("--file", type=str, 
                       help="Caminho completo para um arquivo específico a ser processado")
    parser.add_argument("--direct", action="store_true", 
                       help="Usar conexão direta com o banco (sem API HTTP)")
    parser.add_argument("--yes", "-y", action="store_true", 
                       help="Executar sem pedir confirmação")
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("🔍 BTG AlphaFeed - Carregador de Notícias (v2 - com OCR de PDF)")
    print("=" * 80)
    
    client = None
    if GEMINI_AVAILABLE:
        try:
            env_path = backend_dir / ".env"
            if env_path.exists():
                load_dotenv(dotenv_path=env_path)
            
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key and NEW_GENAI_AVAILABLE:
                # Inicializa o novo cliente (google-genai) com File API e models (como no poc_silva.py)
                client = genai_new.Client(api_key=api_key)
                print("✅ Cliente Gemini (novo SDK) configurado com sucesso.")
            elif api_key and not NEW_GENAI_AVAILABLE:
                print("⚠️ AVISO: SDK novo (google-genai) não está instalado. Instale com: pip install google-genai")
                print("   PDFs usarão extração de texto simples até a instalação do novo SDK.")
            else:
                print("⚠️ AVISO: GEMINI_API_KEY não encontrada. PDFs usarão extração de texto simples.")
        except Exception as e:
            print(f"❌ Erro ao configurar o cliente Gemini: {e}")
            client = None
    
    # CORREÇÃO: O cliente Gemini é passado na inicialização do FileLoader
    try:
        loader = FileLoader(
            files_directory=args.dir,
            client=client
        )
    except FileNotFoundError as e:
        print(f"❌ ERRO: {e}")
        return 1
    
    usar_api = not args.direct
    if usar_api:
        print("🔗 Modo de envio: API HTTP")
        if not loader.verificar_api_status():
             print("\n❌ ERRO: API não está disponível. Verifique se o backend está rodando ou use --direct.")
             return 1
    else:
        print("💾 Modo de envio: Direto no Banco de Dados")

    # --- Lógica de Execução ---
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"❌ ERRO: Arquivo especificado não encontrado: {file_path}")
            return 1
        
        print(f"\n📄 Processando arquivo específico: {file_path.name}")
        if not args.yes:
            if input(f"❓ Confirmar o carregamento de '{file_path.name}'? (s/N): ").lower() not in ['s','y']:
                print("❌ Carregamento cancelado.")
                return 0
        
        artigos_carregados = loader.processar_arquivo(file_path, usar_api)
        print(f"\n✅ SUCESSO: {artigos_carregados} artigos brutos carregados de {file_path.name}")
    else:
        print(f"\n📁 Processando diretório completo: {loader.files_directory}")
        if not args.yes:
            if input(f"❓ Confirmar o carregamento? (s/N): ").lower() not in ['s','y']:
                print("❌ Carregamento cancelado.")
                return 0

        stats = loader.processar_diretorio(usar_api=usar_api)
        
        print("\n" + "="*35 + " RESUMO FINAL " + "="*34)
        print(f"  📁 Arquivos processados: {stats['arquivos_processados']}")
        print(f"  📰 Total de artigos brutos carregados: {stats['artigos_criados']}")
        print(f"  💡 Próximo passo: Execute 'python process_articles.py' para analisar e resumir.")
        print("="*80)
        
    return 0


if __name__ == "__main__":
    sys.exit(main()) 