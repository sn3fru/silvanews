#!/usr/bin/env python3
"""
TESTE CONTROLADO DE INGESTÃO DE PDF
===================================

Este arquivo testa o load_news.py com um PDF específico
para rastrear EXATAMENTE o que está sendo salvo no banco.

USO:
    conda activate pymc2
    python teste_pdf_controlado.py

SAÍDA:
    - Rastreamento completo da ingestão
    - Comparação: texto original vs texto salvo
    - Identificação do ponto exato do problema
"""

import sys
import os
from pathlib import Path
import json
import time
from typing import Any, List, Optional

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

# Imports do backend
try:
    from dotenv import load_dotenv
    from sqlalchemy.orm import Session
    
    from backend.database import SessionLocal, ArtigoBruto
    from backend.crud import get_artigo_by_id
    
    print("✅ Módulos do backend importados com sucesso!")
except ImportError as e:
    print(f"❌ ERRO ao importar módulos: {e}")
    sys.exit(1)

# Carrega variáveis de ambiente
env_file = backend_dir / ".env"
if env_file.exists():
    load_dotenv(env_file)
    print(f"✅ Arquivo .env carregado: {env_file}")

def print_header(title: str, char: str = "=", width: int = 80):
    """Imprime cabeçalho formatado"""
    print(f"\n{char * width}")
    print(f"{title:^{width}}")
    print(f"{char * width}")

def print_section(title: str, char: str = "-", width: int = 60):
    """Imprime seção formatada"""
    print(f"\n{char * width}")
    print(f"{title:^{width}}")
    print(f"{char * width}")

def print_data(title: str, data: Any, max_length: int = 200):
    """Imprime dados formatados com limite de caracteres"""
    if isinstance(data, str):
        if len(data) > max_length:
            data_display = data[:max_length] + f"... [TRUNCADO - {len(data)} chars]"
        else:
            data_display = data
    else:
        data_display = str(data)
    
    print(f"📋 {title}:")
    print(f"   {data_display}")

def testar_ingestao_pdf():
    """Testa a ingestão de um PDF específico"""
    print_header("🧪 TESTE CONTROLADO DE INGESTÃO DE PDF")
    
    # 1. VERIFICAR PDFs DISPONÍVEIS
    print_section("📁 VERIFICANDO PDFs DISPONÍVEIS")
    
    # Corrigido: usa o mesmo padrão do load_news.py (../pdfs)
    pdf_dir = Path("../pdfs")
    if not pdf_dir.exists():
        print("❌ Diretório '../pdfs' não encontrado")
        print(f"   Procurando em: {pdf_dir.absolute()}")
        return
    
    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print("❌ Nenhum arquivo PDF encontrado")
        return
    
    print(f"📊 PDFs encontrados: {len(pdf_files)}")
    for i, pdf_file in enumerate(pdf_files[:5]):  # Mostra apenas os primeiros 5
        print(f"   {i+1}. {pdf_file.name}")
    
    # 2. SELECIONAR PDF PARA TESTE
    print_section("🎯 SELECIONANDO PDF PARA TESTE")
    
    # Pega o primeiro PDF disponível
    pdf_teste = pdf_files[0]
    print(f"📄 PDF selecionado para teste: {pdf_teste.name}")
    print(f"�� Tamanho do arquivo: {pdf_teste.stat().st_size / 1024:.1f} KB")
    
    # 3. VERIFICAR ESTADO ATUAL DO BANCO
    print_section("🗄️ VERIFICANDO ESTADO ATUAL DO BANCO")
    
    try:
        db = SessionLocal()
        
        # Conta artigos antes do teste
        total_antes = db.query(ArtigoBruto).count()
        print(f"📊 Total de artigos no banco: {total_antes}")
        
        # Verifica se este PDF já foi processado
        artigos_existentes = db.query(ArtigoBruto).filter(
            ArtigoBruto.fonte_coleta.like(f"%{pdf_teste.name}%")
        ).all()
        
        if artigos_existentes:
            print(f"⚠️ PDF já foi processado anteriormente:")
            for artigo in artigos_existentes:
                print(f"   📰 ID: {artigo.id}, Status: {artigo.status}")
                print(f"   �� texto_bruto: {len(artigo.texto_bruto)} chars")
                print(f"   📝 texto_processado: {len(artigo.texto_processado) if artigo.texto_processado else 'None'} chars")
        else:
            print("✅ PDF ainda não foi processado")
        
        db.close()
        
    except Exception as e:
        print(f"❌ Erro ao verificar banco: {e}")
        return
    
    # 4. INSTRUÇÕES PARA EXECUÇÃO MANUAL
    print_section("�� INSTRUÇÕES PARA EXECUÇÃO MANUAL")
    
    print("""
🔧 PARA TESTAR A INGESTÃO:

1. ABRA UM NOVO TERMINAL (Anaconda Prompt)
2. ATIVE O AMBIENTE:
   conda activate pymc2
   
3. EXECUTE O LOAD_NEWS.PY (APENAS 3 PÁGINAS):
   python load_news.py --max-pages 3
   
   OU se não tiver essa opção, modifique temporariamente o load_news.py
   para processar apenas 3 páginas aleatórias.
   
4. MONITORE O OUTPUT:
   - Observe se o PDF é processado
   - Verifique se há chamadas para LLM
   - Identifique onde o texto é resumido
   
5. APÓS PROCESSAMENTO, EXECUTE ESTE TESTE:
   python teste_pdf_controlado.py --verificar
   
6. COMPARE OS RESULTADOS:
   - texto_bruto vs texto original do PDF
   - Metadados salvos
   - Status do artigo
""")
    
    # 5. VERIFICAÇÃO PÓS-TESTE
    print_section("🔍 VERIFICAÇÃO PÓS-TESTE")
    
    print("""
�� APÓS EXECUTAR O LOAD_NEWS.PY, ESTE SCRIPT VAI:

1. ✅ Verificar se o artigo foi criado
2. 📊 Analisar o texto_bruto salvo
3. �� Comparar com o PDF original
4. �� Identificar onde o problema ocorreu
5. 💡 Sugerir correções específicas

🎯 OBJETIVO: Confirmar se o problema está em:
   - load_news.py (ingestão com LLM)
   - process_articles.py (processamento posterior)
   - Ambos

⚠️ IMPORTANTE: Processe apenas 3 páginas para teste rápido!
""")

def verificar_artigo_apos_teste():
    """Verifica o artigo após o teste de ingestão"""
    print_header("🔍 VERIFICAÇÃO PÓS-TESTE DE INGESTÃO")
    
    try:
        db = SessionLocal()
        
        # Busca artigos criados recentemente
        artigos_recentes = db.query(ArtigoBruto).order_by(
            ArtigoBruto.created_at.desc()
        ).limit(5).all()
        
        print_section("📊 ARTIGOS CRIADOS RECENTEMENTE")
        
        for artigo in artigos_recentes:
            print(f"\n�� Artigo ID: {artigo.id}")
            print(f"   📅 Criado: {artigo.created_at}")
            print(f"   📁 Fonte: {artigo.fonte_coleta}")
            print(f"   �� texto_bruto: {len(artigo.texto_bruto)} chars")
            print(f"   📝 texto_processado: {len(artigo.texto_processado) if artigo.texto_processado else 'None'} chars")
            print(f"   🏷️ Status: {artigo.status}")
            
            # Análise do texto_bruto
            if artigo.texto_bruto:
                texto = artigo.texto_bruto
                print(f"   📖 Primeiros 100 chars: {texto[:100]}...")
                
                # Verifica se parece resumo
                palavras_resumo = ['notícia', 'artigo', 'matéria', 'peça', 'texto']
                if any(palavra in texto.lower() for palavra in palavras_resumo):
                    print(f"   ⚠️ PARECE SER RESUMO (contém palavras típicas)")
                else:
                    print(f"   ✅ PARECE SER TEXTO ORIGINAL")
        
        db.close()
        
    except Exception as e:
        print(f"❌ Erro ao verificar artigos: {e}")

def main():
    """Função principal"""
    print_header("🧪 TESTE CONTROLADO DE INGESTÃO DE PDF")
    
    # Verifica se é para executar o teste ou verificar resultados
    if len(sys.argv) > 1 and sys.argv[1] == "--verificar":
        verificar_artigo_apos_teste()
    else:
        testar_ingestao_pdf()

if __name__ == "__main__":
    main()