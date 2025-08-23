#!/usr/bin/env python3
"""
Teste das funções de BI
"""

import sys
import os

# Adiciona o diretório backend ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

try:
    from crud import agg_estatisticas_gerais, agg_noticias_por_tag, agg_noticias_por_prioridade
    print("✅ Funções importadas com sucesso!")
    
    # Testa se as funções existem
    print(f"agg_estatisticas_gerais: {agg_estatisticas_gerais.__name__}")
    print(f"agg_noticias_por_tag: {agg_noticias_por_tag.__name__}")
    print(f"agg_noticias_por_prioridade: {agg_noticias_por_prioridade.__name__}")
    
    print("\n✅ Todas as funções estão disponíveis!")
    
except ImportError as e:
    print(f"❌ Erro ao importar: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Erro inesperado: {e}")
    sys.exit(1)
