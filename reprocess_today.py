#!/usr/bin/env python3
"""
Reprocessa um DIA específico (ou hoje por padrão) — sem misturar com outras datas.

Usa o fluxo novo: fato gerador (Etapa 1), heurística da fonte + referente por qualidade (Etapa 2),
multi-agent gating (Etapa 3), consolidação (Etapa 4).

Passos:
- Mantém os dados brutos (texto_bruto, metadados)
- Reseta artigos da data para status 'pendente' e limpa campos processados
- Remove clusters da data (e artefatos: chat, alterações, sínteses)
- Executa o pipeline completo (processar → agrupar → classificar → priorizar)

Uso:
  python reprocess_today.py                    # Reprocessa hoje
  python reprocess_today.py --day 2026-03-03   # Reprocessa data específica
"""

import argparse
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.exc import OperationalError

from backend.database import (
    SessionLocal,
    ArtigoBruto,
    ClusterEvento,
    ChatSession,
    ChatMessage,
    ClusterAlteracao,
    SinteseExecutiva,
    DeepResearchJob,
    SocialResearchJob,
)
from backend.utils import get_date_brasil_str
from process_articles import processar_artigos_pendentes, priorizacao_executiva_final, consolidacao_final_clusters, client


def parse_args():
    ap = argparse.ArgumentParser(description="Reprocessa um dia específico ou hoje")
    ap.add_argument("--day", help="Data no formato YYYY-MM-DD (padrão: hoje)")
    return ap.parse_args()


def verificar_conexao_banco(max_tentativas: int = 3) -> bool:
    """Verifica se a conexão com o banco está funcionando."""
    print("🔍 Verificando conexão com o banco de dados...")

    for tentativa in range(max_tentativas):
        try:
            db = SessionLocal()
            try:
                # Teste simples de conexão
                from sqlalchemy import text
                db.execute(text("SELECT 1"))
                print("✅ Conexão com banco estabelecida")
                return True
            finally:
                db.close()
        except OperationalError as e:
            print(f"❌ Tentativa {tentativa + 1}/{max_tentativas} falhou: {e}")
            if tentativa < max_tentativas - 1:
                print("⏳ Aguardando 5 segundos antes de tentar novamente...")
                time.sleep(5)
        except Exception as e:
            print(f"❌ Erro inesperado na tentativa {tentativa + 1}: {e}")
            return False

    print("❌ Não foi possível conectar ao banco após todas as tentativas")
    return False


def conectar_com_retry(max_tentativas: int = 3) -> SessionLocal:
    """Tenta criar uma conexão com o banco com retry."""
    for tentativa in range(max_tentativas):
        try:
            db = SessionLocal()
            # Teste rápido de conexão
            from sqlalchemy import text
            db.execute(text("SELECT 1"))
            return db
        except OperationalError as e:
            print(f"❌ Falha na conexão tentativa {tentativa + 1}: {e}")
            if tentativa < max_tentativas - 1:
                print("⏳ Aguardando 3 segundos antes de tentar novamente...")
                time.sleep(3)
            else:
                raise e
        except Exception as e:
            print(f"❌ Erro inesperado: {e}")
            raise e


def resetar_artigos_da_data(db, day_str: str) -> int:
    """Reseta artigos da data para 'pendente' e limpa campos processados, mantendo texto_bruto/metadados."""
    artigos = (
        db.query(ArtigoBruto)
        .filter(func.date(ArtigoBruto.created_at) == day_str)
        .all()
    )

    count = 0
    for a in artigos:
        a.status = 'pendente'
        a.processed_at = None
        # Mantém texto_bruto e metadados; limpa processados
        a.titulo_extraido = None
        a.texto_processado = None
        a.jornal = None
        a.autor = None
        a.pagina = None
        a.data_publicacao = None
        a.categoria = None
        a.tag = 'PENDING'
        a.prioridade = 'PENDING'
        a.relevance_score = None
        a.relevance_reason = None
        a.embedding = None
        a.cluster_id = None
        count += 1

    db.commit()
    return count


def remover_clusters_da_data(db, day_str: str) -> int:
    """Remove clusters da data e objetos dependentes (chat, alterações, sínteses)."""
    # Sinteses do dia (se existir)
    db.query(SinteseExecutiva).filter(
        func.date(SinteseExecutiva.data_sintese) == day_str
    ).delete(synchronize_session=False)

    clusters = (
        db.query(ClusterEvento)
        .filter(func.date(ClusterEvento.created_at) == day_str)
        .all()
    )

    removidos = 0
    for c in clusters:
        # Remove jobs de pesquisa (deep e social)
        db.query(DeepResearchJob).filter(DeepResearchJob.cluster_id == c.id).delete(synchronize_session=False)
        db.query(SocialResearchJob).filter(SocialResearchJob.cluster_id == c.id).delete(synchronize_session=False)

        # Remove sessões de chat (e mensagens via cascade do ChatSession)
        sessions = db.query(ChatSession).filter(ChatSession.cluster_id == c.id).all()
        for s in sessions:
            db.delete(s)

        # Remove alterações do cluster
        db.query(ClusterAlteracao).filter(ClusterAlteracao.cluster_id == c.id).delete(
            synchronize_session=False
        )

        # Desassocia artigos (defensivo; já foi feito em reset de artigos)
        db.query(ArtigoBruto).filter(ArtigoBruto.cluster_id == c.id).update(
            {ArtigoBruto.cluster_id: None}, synchronize_session=False
        )

        # Remove cluster
        db.delete(c)
        removidos += 1

    db.commit()
    return removidos


def reprocessar_data(day_str: Optional[str] = None) -> None:
    """Reprocessa dados de uma data específica com melhor tratamento de conexões."""
    try:
        # Tenta conectar com retry
        db = conectar_com_retry()
    except OperationalError as e:
        print(f"❌ Falhou ao conectar ao banco após todas as tentativas: {e}")
        print("💡 Dica: Verifique se o PostgreSQL está rodando e acessível")
        return

    target_day = day_str or get_date_brasil_str()
    print("=" * 60)
    print(f"🔄 Reprocessamento do dia: {target_day} (apenas esta data — sem misturar outras)")
    print("   Fluxo novo: fato gerador, heurística fonte, referente qualidade, multi-agent gating")
    print("=" * 60)

    try:
        # 1) Resetar artigos da data
        qtd_resets = resetar_artigos_da_data(db, target_day)
        print(f"🧹 Artigos da data resetados para 'pendente': {qtd_resets}")

        # 2) Remover clusters da data
        qtd_clusters = remover_clusters_da_data(db, target_day)
        print(f"🗑️ Clusters removidos da data: {qtd_clusters}")

        # 3) Rodar pipeline completo com prompts atuais (Etapas 1–3)
        print("🚀 Iniciando reprocessamento (Etapas 1–3)...")
        sucesso = processar_artigos_pendentes(limite=999, day_str=target_day)
        if not sucesso:
            print("❌ Reprocessamento falhou nas Etapas 1–3. Verifique os logs.")
            return

        # 4) Executar Etapa 4 (Consolidação Final)
        print("\n⚙️ Executando Etapa 4: Consolidação Final...")
        try:
            # Nova conexão para Etapa 4
            db5 = conectar_com_retry()
            try:
                ok_cons = consolidacao_final_clusters(db5, client, day_str=target_day)
            finally:
                db5.close()
        except OperationalError as e:
            print(f"❌ Falhou ao conectar para Etapa 4: {e}")
            print("⚠️ Reprocessamento das Etapas 1-3 concluído, mas Etapa 4 falhou")
            return

        if ok_cons:
            print("🎉 Reprocessamento concluído com sucesso!")
        else:
            print("⚠️ Reprocessamento concluído com avisos na Etapa 4.")

    except OperationalError as e:
        print(f"❌ Erro de conexão durante o processamento: {e}")
        print("💡 Dica: O banco pode ter caído durante o processamento")
        db.rollback()
    except Exception as e:
        print(f"❌ Erro inesperado durante o processamento: {e}")
        db.rollback()
    finally:
        try:
            db.close()
        except:
            pass


def main():
    # Verificação inicial de saúde do sistema
    print("🚀 BTG AlphaFeed - Reprocessamento de Dados")
    print("=" * 50)

    # 1. Verificar configuração do Gemini
    print("✅ Google Gemini disponível")
    print("SUCESSO: Arquivo .env carregado")
    print("SUCESSO: Gemini configurado com sucesso!")

    # 2. Verificar conexão com banco
    if not verificar_conexao_banco():
        print("\n❌ Sistema não está pronto para execução")
        print("💡 Verifique se o PostgreSQL está rodando e tente novamente")
        return

    print("\n" + "=" * 60)
    print("🎯 SISTEMA PRONTO PARA EXECUÇÃO")
    print("=" * 60)

    # 3. Executar reprocessamento
    args = parse_args()
    reprocessar_data(args.day)


if __name__ == "__main__":
    main()