#!/usr/bin/env python3
"""
INVESTIGAÇÃO PROFUNDA DO FLUXO DE DADOS
========================================

Este arquivo investiga NO MÍNIMO DETALHE:
1. O que load_news.py está salvando em texto_bruto
2. Se process_articles.py está alterando texto_bruto
3. Onde exatamente os dados estão sendo perdidos

NÃO ALTERA NENHUM CÓDIGO - APENAS INVESTIGA!
"""

import sys
import os
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import json

# Adiciona o diretório backend ao path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

# Imports do backend
try:
    from dotenv import load_dotenv
    from sqlalchemy.orm import Session
    from sqlalchemy import func, text
    
    from backend.database import SessionLocal, ArtigoBruto, ClusterEvento
    from backend.crud import (
        get_artigos_by_cluster, get_cluster_by_id, get_artigos_pendentes
    )
    
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

def investigar_artigo_especifico(artigo_id: int):
    """Investiga um artigo específico em TODOS os detalhes"""
    print_header(f"🔬 INVESTIGAÇÃO PROFUNDA DO ARTIGO {artigo_id}")
    
    try:
        db = SessionLocal()
        
        # Busca o artigo
        artigo = db.query(ArtigoBruto).filter(ArtigoBruto.id == artigo_id).first()
        if not artigo:
            print(f"❌ Artigo {artigo_id} não encontrado")
            return
        
        print_section("📊 DADOS BÁSICOS DO ARTIGO")
        print_data("ID", artigo.id)
        print_data("Hash Único", artigo.hash_unico)
        print_data("Fonte de Coleta", artigo.fonte_coleta)
        print_data("Status", artigo.status)
        print_data("Criado em", artigo.created_at)
        print_data("Processado em", artigo.processed_at)
        print_data("Cluster ID", artigo.cluster_id)
        
        # ANÁLISE DETALHADA DO TEXTO BRUTO
        print_section("📖 ANÁLISE DETALHADA DO TEXTO BRUTO")
        if artigo.texto_bruto:
            texto_bruto = artigo.texto_bruto
            print(f"�� Tamanho: {len(texto_bruto)} caracteres")
            print(f"📝 Primeiros 200 chars: {texto_bruto[:200]}")
            print(f"�� Últimos 200 chars: {texto_bruto[-200:]}")
            
            # Análise de conteúdo
            if len(texto_bruto) < 500:
                print("⚠️ TEXTO MUITO CURTO - provavelmente resumo, não texto original")
            elif len(texto_bruto) < 2000:
                print("⚠️ TEXTO CURTO - pode ser resumo ou texto truncado")
            else:
                print("✅ TEXTO LONGO - pode ser texto original")
            
            # Verifica se parece resumo
            palavras_resumo = ['notícia', 'matéria', 'artigo', 'peça', 'apresenta', 'incluindo']
            if any(palavra in texto_bruto.lower() for palavra in palavras_resumo):
                print("🚨 PARECE SER RESUMO (contém palavras típicas de resumo)")
            else:
                print("✅ PARECE SER TEXTO ORIGINAL (não contém palavras de resumo)")
                
        else:
            print("❌ TEXTO BRUTO: NÃO DEFINIDO")
        
        # ANÁLISE DETALHADA DO TEXTO PROCESSADO
        print_section("📝 ANÁLISE DETALHADA DO TEXTO PROCESSADO")
        if artigo.texto_processado:
            texto_processado = artigo.texto_processado
            print(f"�� Tamanho: {len(texto_processado)} caracteres")
            print(f"📝 Primeiros 200 chars: {texto_processado[:200]}")
            print(f"�� Últimos 200 chars: {texto_processado[-200:]}")
            
            # Análise de conteúdo
            if len(texto_processado) < 500:
                print("✅ TEXTO CURTO - provavelmente resumo (correto)")
            else:
                print("⚠️ TEXTO LONGO - pode ser texto original (incorreto)")
                
        else:
            print("❌ TEXTO PROCESSADO: NÃO DEFINIDO")
        
        # COMPARAÇÃO DETALHADA
        print_section("🔍 COMPARAÇÃO DETALHADA")
        if artigo.texto_bruto and artigo.texto_processado:
            if artigo.texto_bruto == artigo.texto_processado:
                print("🚨 PROBLEMA CRÍTICO: texto_bruto e texto_processado são IDÊNTICOS!")
                print("   Isso significa que:")
                print("   - OU ambos contêm resumos (texto_bruto deveria ter texto original)")
                print("   - OU ambos contêm texto original (texto_processado deveria ter resumo)")
            else:
                print("✅ OK: texto_bruto e texto_processado são diferentes")
                
                # Verifica qual é qual
                if len(artigo.texto_bruto) > len(artigo.texto_processado):
                    print("   ✅ texto_bruto > texto_processado (correto)")
                else:
                    print("   ⚠️ texto_processado > texto_bruto (pode estar incorreto)")
                    
                # Verifica similaridade
                from difflib import SequenceMatcher
                similaridade = SequenceMatcher(None, artigo.texto_bruto, artigo.texto_processado).ratio()
                print(f"   �� Similaridade entre os textos: {similaridade:.2%}")
                
                if similaridade > 0.8:
                    print("   ⚠️ ATENÇÃO: Textos muito similares (pode haver problema)")
                elif similaridade < 0.3:
                    print("   ✅ OK: Textos bem diferentes (correto)")
                else:
                    print("   ⚠️ ATENÇÃO: Textos moderadamente similares")
        
        # ANÁLISE DOS METADADOS
        print_section("🔧 ANÁLISE DETALHADA DOS METADADOS")
        if artigo.metadados:
            metadados = artigo.metadados
            print("📋 Metadados disponíveis:")
            for chave, valor in metadados.items():
                if isinstance(valor, str) and len(valor) > 100:
                    print(f"   {chave}: {valor[:100]}... [TRUNCADO - {len(valor)} chars]")
                else:
                    print(f"   {chave}: {valor}")
            
            # Verifica campos importantes
            campos_importantes = ['texto_completo', 'arquivo_origem', 'tipo_arquivo', 'data_processamento']
            for campo in campos_importantes:
                if campo in metadados:
                    print(f"✅ Campo '{campo}' encontrado: {metadados[campo]}")
                else:
                    print(f"❌ Campo '{campo}' NÃO encontrado")
                    
            # Verifica se tem texto completo nos metadados
            if 'texto_completo' in metadados:
                texto_completo_meta = metadados['texto_completo']
                print(f"\n�� TEXTO COMPLETO dos metadados:")
                print(f"   �� Tamanho: {len(texto_completo_meta)} caracteres")
                print(f"   📝 Primeiros 200 chars: {texto_completo_meta[:200]}")
                
                # Compara com texto_bruto
                if artigo.texto_bruto:
                    if texto_completo_meta == artigo.texto_bruto:
                        print("   ✅ texto_completo dos metadados = texto_bruto (correto)")
                    else:
                        print("   🚨 PROBLEMA: texto_completo dos metadados ≠ texto_bruto")
                        print("   Isso significa que o texto_bruto foi alterado após a ingestão!")
                        
                        # Verifica qual é mais longo
                        if len(texto_completo_meta) > len(artigo.texto_bruto):
                            print("   �� texto_completo dos metadados > texto_bruto")
                            print("   �� PROBLEMA: texto_bruto foi TRUNCADO ou RESUMIDO!")
                        else:
                            print("   �� texto_completo dos metadados < texto_bruto")
                            print("   ⚠️ ATENÇÃO: texto_bruto foi EXPANDIDO (pode estar incorreto)")
            else:
                print("❌ Campo 'texto_completo' NÃO encontrado nos metadados")
                
        else:
            print("❌ METADADOS: NÃO DEFINIDO")
        
        # ANÁLISE DO FLUXO
        print_section("🔄 ANÁLISE DO FLUXO DE PROCESSAMENTO")
        
        # Verifica se foi processado
        if artigo.status == 'processado':
            print("�� Status: processado")
            print("   ✅ Artigo foi processado pelo process_articles.py")
            
            # Verifica se tem cluster
            if artigo.cluster_id:
                print(f"   🔗 Associado ao cluster {artigo.cluster_id}")
                
                # Busca dados do cluster
                cluster = get_cluster_by_id(db, artigo.cluster_id)
                if cluster:
                    print(f"   �� Título do cluster: {cluster.titulo_cluster}")
                    if cluster.resumo_cluster:
                        print(f"   �� Resumo do cluster: {cluster.resumo_cluster[:200]}...")
                    else:
                        print("   ❌ Cluster sem resumo")
                else:
                    print("   ❌ Cluster não encontrado")
            else:
                print("   ❌ NÃO associado a cluster")
        else:
            print(f"📊 Status: {artigo.status}")
            print("   ⚠️ Artigo NÃO foi processado ainda")
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ ERRO ao investigar artigo: {e}")
        import traceback
        traceback.print_exc()
        return False

def investigar_artigos_por_fonte():
    """Investiga artigos por fonte de coleta para entender padrões"""
    print_header("�� INVESTIGAÇÃO POR FONTE DE COLETA")
    
    try:
        db = SessionLocal()
        
        # Busca fontes de coleta únicas
        query = text("""
            SELECT 
                fonte_coleta,
                COUNT(*) as total,
                COUNT(CASE WHEN texto_bruto IS NOT NULL THEN 1 END) as com_texto_bruto,
                COUNT(CASE WHEN texto_processado IS NOT NULL THEN 1 END) as com_texto_processado,
                AVG(LENGTH(texto_bruto)) as avg_tamanho_bruto,
                AVG(LENGTH(texto_processado)) as avg_tamanho_processado,
                MIN(created_at) as primeiro,
                MAX(created_at) as ultimo
            FROM artigos_brutos
            GROUP BY fonte_coleta
            ORDER BY total DESC
            LIMIT 10
        """)
        
        fontes = db.execute(query).fetchall()
        
        print("📊 Análise por fonte de coleta:")
        for fonte in fontes:
            print(f"\n📰 FONTE: {fonte.fonte_coleta}")
            print(f"   📊 Total: {fonte.total}")
            print(f"   �� Com texto_bruto: {fonte.com_texto_bruto}")
            print(f"   📝 Com texto_processado: {fonte.com_texto_processado}")
            print(f"   📏 Tamanho médio texto_bruto: {fonte.avg_tamanho_bruto:.0f} chars")
            print(f"   📏 Tamanho médio texto_processado: {fonte.avg_tamanho_processado:.0f} chars")
            print(f"   📅 Período: {fonte.primeiro} até {fonte.ultimo}")
            
            # Análise de padrão
            if fonte.avg_tamanho_bruto < 1000:
                print("   ⚠️ ATENÇÃO: texto_bruto muito curto (pode ser resumo)")
            elif fonte.avg_tamanho_bruto > 5000:
                print("   ✅ OK: texto_bruto longo (pode ser texto original)")
            else:
                print("   ⚠️ ATENÇÃO: texto_bruto tamanho médio (pode estar truncado)")
                
            if fonte.avg_tamanho_processado > 1000:
                print("   ⚠️ ATENÇÃO: texto_processado muito longo (pode ser texto original)")
            else:
                print("   ✅ OK: texto_processado curto (pode ser resumo)")
        
        db.close()
        
    except Exception as e:
        print(f"❌ ERRO ao investigar por fonte: {e}")

def investigar_artigos_por_tipo():
    """Investiga artigos por tipo de arquivo (PDF vs JSON)"""
    print_header("�� INVESTIGAÇÃO POR TIPO DE ARQUIVO")
    
    try:
        db = SessionLocal()
        
        # Busca artigos com metadados que indiquem tipo
        query = text("""
            SELECT 
                metadados->>'tipo_arquivo' as tipo,
                COUNT(*) as total,
                AVG(LENGTH(texto_bruto)) as avg_tamanho_bruto,
                AVG(LENGTH(texto_processado)) as avg_tamanho_processado,
                COUNT(CASE WHEN LENGTH(texto_bruto) < 1000 THEN 1 END) as texto_bruto_curto,
                COUNT(CASE WHEN LENGTH(texto_bruto) > 5000 THEN 1 END) as texto_bruto_longo
            FROM artigos_brutos
            WHERE metadados IS NOT NULL
            GROUP BY metadados->>'tipo_arquivo'
            ORDER BY total DESC
        """)
        
        tipos = db.execute(query).fetchall()
        
        print("📊 Análise por tipo de arquivo:")
        for tipo in tipos:
            if not tipo.tipo:
                continue
                
            print(f"\n📁 TIPO: {tipo.tipo}")
            print(f"   �� Total: {tipo.total}")
            print(f"   📏 Tamanho médio texto_bruto: {tipo.avg_tamanho_bruto:.0f} chars")
            print(f"   📏 Tamanho médio texto_processado: {tipo.avg_tamanho_processado:.0f} chars")
            print(f"   ⚠️ texto_bruto curto (<1000): {tipo.texto_bruto_curto}")
            print(f"   ✅ texto_bruto longo (>5000): {tipo.texto_bruto_longo}")
            
            # Análise específica por tipo
            if tipo.tipo == 'pdf':
                if tipo.avg_tamanho_bruto < 2000:
                    print("   �� PROBLEMA: PDFs com texto_bruto muito curto!")
                    print("   💡 Isso sugere que o OCR/LLM está resumindo em vez de extrair texto completo")
                else:
                    print("   ✅ OK: PDFs com texto_bruto longo (texto completo extraído)")
                    
            elif tipo.tipo == 'json':
                if tipo.avg_tamanho_bruto > 2000:
                    print("   ✅ OK: JSONs com texto_bruto longo (texto completo preservado)")
                else:
                    print("   ⚠️ ATENÇÃO: JSONs com texto_bruto curto (pode estar sendo processado)")
        
        db.close()
        
    except Exception as e:
        print(f"❌ ERRO ao investigar por tipo: {e}")

def investigar_artigos_recentes():
    """Investiga artigos criados recentemente para entender o padrão atual"""
    print_header("🕐 INVESTIGAÇÃO DE ARTIGOS RECENTES")
    
    try:
        db = SessionLocal()
        
        # Busca artigos das últimas 24h
        query = text("""
            SELECT 
                id,
                fonte_coleta,
                metadados->>'tipo_arquivo' as tipo,
                LENGTH(texto_bruto) as tamanho_bruto,
                LENGTH(texto_processado) as tamanho_processado,
                status,
                created_at
            FROM artigos_brutos
            WHERE created_at >= NOW() - INTERVAL '24 hours'
            ORDER BY created_at DESC
            LIMIT 20
        """)
        
        artigos_recentes = db.execute(query).fetchall()
        
        print(f"📊 Artigos criados nas últimas 24h: {len(artigos_recentes)}")
        
        for artigo in artigos_recentes:
            print(f"\n�� Artigo {artigo.id} ({artigo.created_at.strftime('%H:%M')})")
            print(f"   📰 Fonte: {artigo.fonte_coleta}")
            print(f"   �� Tipo: {artigo.tipo or 'N/A'}")
            print(f"   📏 Tamanho texto_bruto: {artigo.tamanho_bruto} chars")
            print(f"   📏 Tamanho texto_processado: {artigo.tamanho_processado} chars")
            print(f"   📊 Status: {artigo.status}")
            
            # Análise rápida
            if artigo.tamanho_bruto < 1000:
                print("   ⚠️ texto_bruto muito curto")
            elif artigo.tamanho_bruto > 5000:
                print("   ✅ texto_bruto longo")
            else:
                print("   ⚠️ texto_bruto tamanho médio")
                
            if artigo.tamanho_processado and artigo.tamanho_processado > 1000:
                print("   ⚠️ texto_processado muito longo")
            elif artigo.tamanho_processado:
                print("   ✅ texto_processado adequado")
            else:
                print("   ❌ texto_processado não definido")
        
        db.close()
        
    except Exception as e:
        print(f"❌ ERRO ao investigar artigos recentes: {e}")

def main():
    """Função principal da investigação"""
    print_header("🔬 INVESTIGAÇÃO PROFUNDA DO FLUXO DE DADOS", "=", 80)
    print(f"📅 Data/Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 1. Investigar artigo específico (do diagnóstico anterior)
    artigo_id = 7108  # Artigo que mostrou problema no diagnóstico
    print(f"\n�� INVESTIGANDO ARTIGO ESPECÍFICO: {artigo_id}")
    investigar_artigo_especifico(artigo_id)
    
    # 2. Investigar por fonte de coleta
    print_header("�� INVESTIGAÇÃO POR FONTE")
    investigar_artigos_por_fonte()
    
    # 3. Investigar por tipo de arquivo
    print_header("�� INVESTIGAÇÃO POR TIPO")
    investigar_artigos_por_tipo()
    
    # 4. Investigar artigos recentes
    print_header("🕐 INVESTIGAÇÃO RECENTE")
    investigar_artigos_recentes()
    
    # 5. RESUMO FINAL
    print_header("�� RESUMO DA INVESTIGAÇÃO", "=", 80)
    print("✅ INVESTIGAÇÃO CONCLUÍDA!")
    print("\n🔍 PRÓXIMOS PASSOS:")
    print("1. Analise os resultados acima")
    print("2. Identifique padrões nos problemas")
    print("3. Determine se o problema está em:")
    print("   - load_news.py (ingestão)")
    print("   - process_articles.py (processamento)")
    print("   - Ambos")
    print("4. Planeje correções específicas")
    
    print("\n🚨 PROBLEMAS ESPERADOS:")
    print("- PDFs sendo processados por LLM na ingestão")
    print("- texto_bruto sendo sobrescrito no processamento")
    print("- Falta de preservação do texto original")
    print("- Metadados não sendo usados corretamente")

if __name__ == "__main__":
    main()