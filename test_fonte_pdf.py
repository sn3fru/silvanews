#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Teste para verificar se as melhorias na extração de fonte de PDFs estão funcionando.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backend.prompts import PROMPT_EXTRACAO_GATEKEEPER_V13

def testar_prompt_fonte_pdf():
    """Testa se o prompt para extração de fonte de PDFs está correto."""
    
    print("🔍 Testando prompt para extração de fonte de PDFs...")
    print("=" * 60)
    
    # Verifica se o prompt contém as instruções para PDFs
    prompt = PROMPT_EXTRACAO_GATEKEEPER_V13
    
    # Verifica se contém as instruções específicas para PDFs
    instrucoes_pdf = [
        "EXTRACAÇÃO DE FONTE PARA PDFs",
        "jornal: Nome do jornal/revista/fonte impressa",
        "autor: Nome do autor/repórter quando disponível",
        "pagina: Número da página ou seção",
        "data: Data de publicação quando disponível",
        "jornal deve ser o nome real do jornal/revista, não o nome do arquivo",
        "autor deve ser extraído do texto quando disponível",
        "pagina deve indicar a página específica onde o artigo aparece",
        "data deve ser a data de publicação da edição, não a data de processamento"
    ]
    
    todas_instrucoes_presentes = True
    for instrucao in instrucoes_pdf:
        if instrucao.lower() in prompt.lower():
            print(f"✅ {instrucao}")
        else:
            print(f"❌ {instrucao}")
            todas_instrucoes_presentes = False
    
    print("=" * 60)
    if todas_instrucoes_presentes:
        print("🎉 Todas as instruções para PDFs estão presentes no prompt!")
    else:
        print("⚠️ Algumas instruções para PDFs estão faltando no prompt.")
    
    return todas_instrucoes_presentes

def testar_formato_saida():
    """Testa se o formato de saída está correto."""
    
    print("\n🔍 Testando formato de saída...")
    print("=" * 60)
    
    prompt = PROMPT_EXTRACAO_GATEKEEPER_V13
    
    # Verifica se o formato de saída inclui os campos necessários
    campos_necessarios = [
        '"jornal":',
        '"autor":',
        '"pagina":',
        '"data":'
    ]
    
    todos_campos_presentes = True
    for campo in campos_necessarios:
        if campo in prompt:
            print(f"✅ Campo {campo} presente no formato de saída")
        else:
            print(f"❌ Campo {campo} ausente no formato de saída")
            todos_campos_presentes = False
    
    print("=" * 60)
    if todos_campos_presentes:
        print("🎉 Todos os campos necessários estão presentes no formato de saída!")
    else:
        print("⚠️ Alguns campos necessários estão faltando no formato de saída.")
    
    return todos_campos_presentes

if __name__ == "__main__":
    print("🚀 Iniciando testes das melhorias na extração de fonte de PDFs...")
    print()
    
    # Testa o prompt
    prompt_ok = testar_prompt_fonte_pdf()
    
    # Testa o formato de saída
    formato_ok = testar_formato_saida()
    
    print("\n" + "=" * 60)
    print("📊 RESUMO DOS TESTES")
    print("=" * 60)
    print(f"Prompt para PDFs: {'✅ OK' if prompt_ok else '❌ FALHOU'}")
    print(f"Formato de saída: {'✅ OK' if formato_ok else '❌ FALHOU'}")
    
    if prompt_ok and formato_ok:
        print("\n🎉 Todos os testes passaram! As melhorias estão funcionando.")
    else:
        print("\n⚠️ Alguns testes falharam. Verifique as implementações.")
