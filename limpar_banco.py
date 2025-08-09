#!/usr/bin/env python3
"""
Script para limpar o banco de dados do BTG AlphaFeed.

Oferece dois modos de operação:
1. Por data: Remove registros em um intervalo de datas específico.
   Uso: --data-inicio YYYY-MM-DD --data-fim YYYY-MM-DD

2. Deleção total: Remove TODOS os registros das tabelas configuradas.
   Uso: --deletar-tudo
   python limpar_banco.py --deletar-tudo
"""

import os
import sys
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
import argparse

# Adiciona o diretório backend ao path para importação dos módulos da aplicação
sys.path.append(os.path.join(os.path.dirname(__file__), 'backend'))

from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import and_

# Importação dos modelos. É crucial importar todos os modelos que serão manipulados.
from backend.database import (
    SessionLocal, 
    ArtigoBruto, 
    ClusterEvento, 
    LogProcessamento, 
    SinteseExecutiva, 
    ChatSession,
    ChatMessage
)
from backend.crud import create_log

# ==============================================================================
# CONFIGURAÇÃO CENTRAL DAS TABELAS
# ==============================================================================
TABELAS_CONFIG: Dict[str, Dict[str, Any]] = {
    'artigos': {'model': ArtigoBruto, 'date_col': 'created_at', 'emoji': '📰'},
    'chat_messages': {'model': ChatMessage, 'date_col': 'timestamp', 'emoji': '✉️'},
    'chat_sessions': {'model': ChatSession, 'date_col': 'created_at', 'emoji': '💬'},
    'clusters': {'model': ClusterEvento, 'date_col': 'created_at', 'emoji': '🔗'},
    'logs': {'model': LogProcessamento, 'date_col': 'timestamp', 'emoji': '📝'},
    'sinteses': {'model': SinteseExecutiva, 'date_col': 'created_at', 'emoji': '📊'}
}

# ==============================================================================
# ORDEM DE EXCLUSÃO
# Define a ordem correta de exclusão para evitar erros de Foreign Key.
# Itens que dependem de outros (filhos) devem vir ANTES dos itens de que dependem (pais).
# ==============================================================================
ORDEM_DE_EXCLUSAO = [
    'chat_messages',  # Deve ser excluído ANTES de 'chat_sessions'
    'chat_sessions',  # Deve ser excluído ANTES de 'clusters'
    'artigos',        # Independente (ordem menos crítica)
    'clusters',       # Dependido por 'chat_sessions'
    'sinteses',       # Independente
    'logs'            # Independente
]


def carregar_configuracao():
    """Carrega configuração do ambiente a partir do arquivo .env."""
    env_path = os.path.join(os.path.dirname(__file__), 'backend', '.env')
    load_dotenv(env_path)
    if not os.getenv('DATABASE_URL'):
        print("❌ DATABASE_URL não configurada no arquivo .env")
        sys.exit(1)
    print("✅ Configuração carregada com sucesso")


def confirmar_limpeza_por_data(db: Session, data_inicio: date, data_fim: date, tabelas: List[str]) -> bool:
    """Solicita confirmação para limpeza baseada em datas."""
    print("\n" + "="*60)
    print("🗑️  CONFIRMAÇÃO DE LIMPEZA DO BANCO DE DADOS (POR DATA)")
    print("="*60)
    print(f"📅 Período: {data_inicio} até {data_fim}")
    print(f"📊 Tabelas afetadas: {', '.join(tabelas)}")
    
    print("\n📈 ESTATÍSTICAS DO PERÍODO:")
    for nome_tabela in tabelas:
        config = TABELAS_CONFIG[nome_tabela]
        model, date_col_name, emoji = config['model'], config['date_col'], config['emoji']
        date_column = getattr(model, date_col_name)
        count = db.query(model).filter(and_(date_column >= data_inicio, date_column <= data_fim + timedelta(days=1))).count()
        print(f"   {emoji} {nome_tabela.capitalize()}: {count}")
    
    print("\n⚠️  ATENÇÃO: Esta operação é IRREVERSÍVEL!")
    resposta = input("\n❓ Confirma a limpeza? (digite 'SIM' para confirmar): ")
    return resposta.upper() == 'SIM'


def confirmar_limpeza_total(db: Session, tabelas: List[str]) -> bool:
    """Solicita confirmação de alto risco para a limpeza TOTAL do banco."""
    frase_confirmacao = "DELETAR TUDO SEM VOLTA"
    print("\n" + "#"*60)
    print("🚨🚨🚨 ALERTA MÁXIMO: DELEÇÃO TOTAL DO BANCO DE DADOS 🚨🚨🚨")
    print("#"*60)
    print("Esta operação irá apagar TODAS as linhas das seguintes tabelas:")
    print(f"   >>> {', '.join(tabelas)} <<<")
    print("Esta ação NÃO PODE SER DESFEITA e resultará em PERDA PERMANENTE DE DADOS.")
    
    print("\n📈 ESTATÍSTICAS TOTAIS (TODOS OS REGISTROS SERÃO APAGADOS):")
    for nome_tabela in tabelas:
        config = TABELAS_CONFIG[nome_tabela]
        model, emoji = config['model'], config['emoji']
        count = db.query(model).count()
        print(f"   {emoji} {nome_tabela.capitalize()}: {count}")
        
    print("\n" + "#"*60)
    resposta = input(f"❓ Para confirmar a exclusão PERMANENTE, digite a frase exata '{frase_confirmacao}': ")
    return resposta == frase_confirmacao


def limpar_tabela(db: Session, model: Any, date_col_name: str = None, data_inicio: date = None, data_fim: date = None) -> int:
    """Função genérica para remover registros. Se não houver datas, apaga tudo."""
    query = db.query(model)
    if date_col_name and data_inicio and data_fim:
        date_column = getattr(model, date_col_name)
        query = query.filter(and_(date_column >= data_inicio, date_column <= data_fim + timedelta(days=1)))
    
    registros_removidos = query.delete(synchronize_session=False)
    return registros_removidos


def executar_limpeza(tabelas: List[str], deletar_tudo: bool, data_inicio: date = None, data_fim: date = None):
    """Orquestra a limpeza, seja total ou por data."""
    
    tabelas_ordenadas = [tabela for tabela in ORDEM_DE_EXCLUSAO if tabela in tabelas]
    modo = "TOTAL" if deletar_tudo else f"por data ({data_inicio} a {data_fim})"

    print(f"\n🔄 Iniciando limpeza {modo} na ordem: {', '.join(tabelas_ordenadas)}")
    
    db = SessionLocal()
    try:
        resultados = {}
        for nome_tabela in tabelas_ordenadas:
            config = TABELAS_CONFIG[nome_tabela]
            print(f"   {config['emoji']} Removendo {nome_tabela}...")
            
            removidos = limpar_tabela(db, config['model'], config['date_col'], data_inicio, data_fim)
            resultados[nome_tabela] = removidos
            
            print(f"     ✅ {removidos} registros removidos")
        
        db.commit()

        create_log(
            db, "WARNING" if deletar_tudo else "INFO", "limpeza_banco", f"Limpeza {modo} executada.",
            {"modo": "total" if deletar_tudo else "data", "resultados": resultados}
        )
        db.commit()
        
        print("\n✅ Limpeza concluída com sucesso!")
        print("📊 Resumo:")
        for tabela, quantidade in resultados.items():
            print(f"   {tabela.capitalize()}: {quantidade} registros removidos")
        
        return True
        
    except Exception as e:
        print(f"❌ Erro durante a limpeza: {e}")
        db.rollback()
        return False
    finally:
        db.close()


def main():
    """Função principal que faz o parse dos argumentos e orquestra a limpeza."""
    parser = argparse.ArgumentParser(
        description="Limpa o banco de dados do BTG AlphaFeed.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    # Grupo para os modos de limpeza
    group = parser.add_argument_group('Modos de Limpeza (escolha um)')
    group.add_argument('--deletar-tudo', action='store_true', help='Apaga TODAS as linhas de TODAS as tabelas configuradas. USE COM EXTREMO CUIDADO.')
    group.add_argument('--data-inicio', type=str, help='Data de início para limpeza (YYYY-MM-DD). Requer --data-fim.')
    group.add_argument('--data-fim', type=str, help='Data de fim para limpeza (YYYY-MM-DD). Requer --data-inicio.')

    parser.add_argument('--tabelas', type=str, nargs='+', choices=list(TABELAS_CONFIG.keys()) + ['tudo'], default=['tudo'], help='Tabelas a serem limpas (default: tudo).')
    parser.add_argument('--confirmar', action='store_true', help='Pula a confirmação. SÓ FUNCIONA PARA LIMPEZA POR DATA. NUNCA para --deletar-tudo.')

    args = parser.parse_args()
    
    # Validação dos argumentos
    if args.deletar_tudo and (args.data_inicio or args.data_fim):
        parser.error("O argumento --deletar-tudo não pode ser usado com --data-inicio ou --data-fim.")
    if (args.data_inicio and not args.data_fim) or (not args.data_inicio and args.data_fim):
        parser.error("Os argumentos --data-inicio e --data-fim devem ser usados juntos.")
    if not args.deletar_tudo and not args.data_inicio:
        parser.error("Você deve especificar um modo de limpeza: --deletar-tudo ou --data-inicio/--data-fim.")

    carregar_configuracao()
    tabelas_a_limpar = list(TABELAS_CONFIG.keys()) if 'tudo' in args.tabelas else args.tabelas
    db = SessionLocal()

    try:
        if args.deletar_tudo:
            if not confirmar_limpeza_total(db, tabelas_a_limpar):
                print("❌ Limpeza total cancelada pelo usuário.")
                sys.exit(0)
            sucesso = executar_limpeza(tabelas_a_limpar, deletar_tudo=True)
        else:
            data_inicio = datetime.strptime(args.data_inicio, '%Y-%m-%d').date()
            data_fim = datetime.strptime(args.data_fim, '%Y-%m-%d').date()
            if data_inicio > data_fim:
                print("❌ Data de início deve ser menor ou igual à data de fim")
                sys.exit(1)
            
            if not args.confirmar:
                if not confirmar_limpeza_por_data(db, data_inicio, data_fim, tabelas_a_limpar):
                    print("❌ Limpeza cancelada pelo usuário.")
                    sys.exit(0)
            
            sucesso = executar_limpeza(tabelas_a_limpar, deletar_tudo=False, data_inicio=data_inicio, data_fim=data_fim)
    finally:
        db.close()

    if sucesso:
        print("\n🎉 Limpeza finalizada!")
    else:
        print("\n❌ Limpeza falhou.")
        sys.exit(1)

if __name__ == "__main__":
    main()