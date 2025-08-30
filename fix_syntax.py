#!/usr/bin/env python3
"""
Script para corrigir problemas de sintaxe no process_articles.py
"""

import re

def fix_process_articles():
    # Lê o arquivo
    with open('process_articles.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Remove linhas órfãs e corrige problemas de sintaxe
    lines = content.split('\n')
    cleaned_lines = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Remove linhas que são apenas strings isoladas
        if line in ['IMPORTANTE: Retorne APENAS o JSON válido para este lote.', '"""']:
            i += 1
            continue

        # Remove linhas com apenas código solto (sem contexto)
        if line in ['prompt_completo,', 'generation_config={', "'temperature': 0.05,  # determinístico", "'top_p': 0.7,", 'max_output_tokens': MAX_OUTPUT_TOKENS_STAGE2,', "'candidate_count': 1,", "'top_k': 10", '}', ')', 'if not response.text:', "print(f'⚠️ AVISO: API retornou resposta vazia para o lote {rotulo} {num_lote}. Pulando este lote.')"]:
            i += 1
            continue

        # Remove blocos de código órfãos
        if line.startswith('print(f"📥 RESPOSTA RECEBIDA'):
            i += 1
            continue

        if line.startswith('grupos_brutos = extrair_grupos_agrupamento_seguro'):
            i += 1
            continue

        if line.startswith('if not grupos_brutos or not isinstance'):
            i += 1
            continue

        if line.startswith('print(f"✅ SUCESSO LOTE'):
            i += 1
            continue

        if line.startswith('for grupo_data in grupos_brutos:'):
            # Pula todo o bloco de processamento de grupos
            indent_level = len(lines[i]) - len(lines[i].lstrip())
            i += 1
            while i < len(lines) and (lines[i].strip() == '' or len(lines[i]) - len(lines[i].lstrip()) > indent_level):
                i += 1
            continue

        cleaned_lines.append(lines[i])
        i += 1

    # Reescreve o arquivo
    with open('process_articles.py', 'w', encoding='utf-8') as f:
        f.write('\n'.join(cleaned_lines))

    print('Arquivo limpo com sucesso!')

if __name__ == "__main__":
    fix_process_articles()
